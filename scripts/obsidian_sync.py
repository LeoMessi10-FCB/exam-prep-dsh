#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""obsidian_sync.py —— exam-prep → Obsidian 的单向派生写入器（v1.5，纯标准库）。

真源：references/obsidian-integration.md。本脚本只做「工作区 → vault」一个方向，
vault 里的任何内容都不回流到六文件工作区、不参与掌握度、不进留出集哈希。

硬边界
- 只写 write_dir（默认 <vault>/ExamPrep/）之内的文件；目标路径经 realpath 解析后必须仍在
  write_dir 下，符号链接逃逸 / `..` / 绝对路径一律拒绝（退出码 1）。
- 只读：<EXAM_PREP_HOME>/obsidian_config.json、工作区 answer_log.csv 与 syllabus_table.csv、
  write_dir 内既有笔记（仅为保留「备注」手写区）、--report / --from / --gap-diff 指定的文件。
  绝不打开 held_out.md，也绝不读取 deny 列表里的用户主权区。
- 生成区由 `%% exam-prep:generated:start … %%` 与 `%% exam-prep:generated:end %%` 包裹；
  区外内容逐字节保留（用户手写区不会被覆盖）。
- 幂等：同输入同日重跑输出逐字节一致（frontmatter 只写 YYYY-MM-DD 粒度；可用 --date 固定）。

写入区解析（v1.5.1，按工作区隔离）
- 优先级：`--write-dir` > `<工作区>/learner_profile.json` 的 `obsidian_write_dir` > 全局配置的 `write_dir`。
- 局部字段**不存在** = 老工作区 → 回退全局；**存在但为空** = 建库时答「不需要」→ 静默跳过（退出码 3）。
- 局部字段永远不写全局配置：不同考试可以写进 vault 的不同文件夹，互不干扰。

子命令
  bind         --vault PATH [--write-dir ExamPrep] [--source DIR ...] [--deny DIR ...] [--dry-run]
  doctor       [--fix]
  push-errors  --workspace <考试目录> --exam ID [--dry-run]
  push-concept --workspace <考试目录> --exam ID --module M --from FILE [--source S ...] [--dry-run]
  push-review  --workspace <考试目录> --exam ID --week 2026-W45 --report FILE [--gap-diff FILE] [--dry-run]
  check        --workspace <考试目录> --exam ID
退出码：0 成功；1 校验失败；2 参数/配置错误；3 vault 不可用（调用方应静默降级，不提示用户装任何东西）。

【Python 不可用时的降级说明】（与其余脚本同口径）
无 Python 时不要手工往 vault 写生成区——手工复刻 frontmatter 与标记极易破坏幂等；
正确降级是**跳过 Obsidian 同步**（它在设计上就是可选增强）：练习、批改、周报、Anki 全部照常，
笔记留到有 Python 的环境再补推。手动检查要点：frontmatter 以 --- 开头结尾、键值一行一对、
日期 YYYY-MM-DD、标签无空格、生成的表格用 | 分隔。
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import sys

CONFIG_NAME = "obsidian_config.json"
LOCAL_KEY = "obsidian_write_dir"   # 工作区 learner_profile.json 里的局部写入区
DEFAULT_WRITE_DIR = "ExamPrep"
START = "%% exam-prep:generated:start"
END = "%% exam-prep:generated:end %%"
# Obsidian 官方文档：链接目标中这些字符会导致链接失效（# | ^ : %% [[ ]]）
FORBIDDEN = set('#|^:%[]')
EXTRA_FORBIDDEN = set('/\\<>"?*')
CORE = ["date", "模块", "题型", "对错", "信心", "错因(CPKG)", "是否留出集"]


def out(msg):
    sys.stdout.write(msg + "\n")


def warn(msg):
    sys.stderr.write("WARN: %s\n" % msg)


def fail(msg):
    sys.stderr.write("FAIL: %s\n" % msg)


# ---------------------------------------------------------------- 配置与路径

def prep_home():
    return os.path.abspath(os.environ.get("EXAM_PREP_HOME")
                           or os.path.join(os.path.expanduser("~"), "exam-prep"))


def config_path():
    return os.path.join(prep_home(), CONFIG_NAME)


def load_config():
    path = config_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        fail("配置无法解析：%s（%s）" % (path, e))
        return None
    if not isinstance(cfg, dict) or not cfg.get("vault_path"):
        fail("配置缺 vault_path：%s" % path)
        return None
    return cfg


def vault_base(cfg):
    return os.path.realpath(os.path.expanduser(cfg["vault_path"]))


def vault_paths(cfg, write_dir=None):
    """返回 (vault 真实路径, 写入区真实路径)；write_dir 缺省取全局配置。"""
    vault = vault_base(cfg)
    wd = write_dir if write_dir else (cfg.get("write_dir") or DEFAULT_WRITE_DIR)
    return vault, os.path.realpath(os.path.join(vault, wd))


def write_dir_problem(cfg, wd):
    """写入区必须落在 vault 内的相对路径上（防绝对路径/../ 把写入区挪出 vault）。"""
    if not wd:
        return "write_dir 为空"
    if os.path.isabs(wd) or wd.replace("\\", "/").split("/")[0] in ("..", ""):
        return "write_dir 必须是 vault 内的相对路径：%s" % wd
    vault = vault_base(cfg)
    write_root = os.path.realpath(os.path.join(vault, wd))
    if write_root == vault or not write_root.startswith(vault + os.sep):
        return "写入区必须 strict 位于 vault 之下（当前解析为 %s）" % write_root
    return None


def config_problem(cfg):
    """全局配置的写入区是否合法（仅 doctor 用来报告，不再阻断单次同步）。"""
    return write_dir_problem(cfg, cfg.get("write_dir") or DEFAULT_WRITE_DIR)


def read_local_write_dir(ws):
    """从 <工作区>/learner_profile.json 读 obsidian_write_dir（v1.5.1 按工作区隔离）。

    返回 (present, value)：
      (False, None) → 老工作区没这个字段：回退全局 write_dir（向后兼容）
      (True, "")    → 建库时答「不需要」：本次考试全部同步静默跳过
      (True, "路径") → 只把笔记写进 vault 的这个子目录
    """
    if not ws:
        return False, None
    path = os.path.join(ws, "learner_profile.json")
    if not os.path.isfile(path):
        return False, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False, None
    if not isinstance(data, dict) or LOCAL_KEY not in data:
        return False, None
    value = data.get(LOCAL_KEY)
    if value is None:
        return True, ""
    return True, str(value).strip()


def resolve_write_dir(cfg, ws, override=None):
    """决定本次写入区。优先级：--write-dir > 工作区局部配置 > 全局 write_dir。

    返回 (write_dir, 退出码)：write_dir 为 None 表示本次不同步（退出码 3）。
    """
    if override is not None:
        wd = override.strip()
        return (wd, 0) if wd else (None, 3)
    present, local = read_local_write_dir(ws)
    if present:
        return (local, 0) if local else (None, 3)
    return cfg.get("write_dir") or DEFAULT_WRITE_DIR, 0


def safe_target(write_root, relpath):
    """把 write_dir 内的相对路径解析为绝对路径；越界即抛 ValueError。"""
    if os.path.isabs(relpath):
        raise ValueError("拒绝绝对路径：%s" % relpath)
    target = os.path.realpath(os.path.join(write_root, relpath))
    root = os.path.realpath(write_root)
    if target != root and not target.startswith(root + os.sep):
        raise ValueError("路径越出写入区：%s" % relpath)
    if os.path.basename(target).lower().startswith("held_out"):
        raise ValueError("留出集相关文件不得进入 vault：%s" % relpath)
    return target


# ---------------------------------------------------------------- 文本工具

def slugify(text, limit=60):
    buf = []
    for ch in (text or "").strip():
        if ch in FORBIDDEN or ch in EXTRA_FORBIDDEN or ch.isspace():
            buf.append("-")
        elif ord(ch) < 32:
            buf.append("-")
        else:
            buf.append(ch)
    s = re.sub(r"-{2,}", "-", "".join(buf)).strip("-.")
    if len(s) > limit:
        s = s[:limit].rstrip("-.")
    return s or "untitled"


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    s = str(value)
    if s == "":
        return '""'
    risky = (s[0] in "-?:,#[]{}&*!|>'\"%@`" or " " in s or ":" in s or "#" in s
             or "\n" in s or s.startswith("[["))
    if risky:
        return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return s


def render_frontmatter(pairs):
    """pairs: [(key, value)]，value 为 str/bool/int/float/None/list。键序即输出序。"""
    lines = ["---"]
    for key, value in pairs:
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                lines.append("%s: []" % key)
                continue
            lines.append("%s:" % key)
            for item in value:
                lines.append("  - %s" % yaml_scalar(item))
        else:
            lines.append("%s: %s" % (key, yaml_scalar(value)))
    lines.append("---")
    return "\n".join(lines) + "\n"


def fm_get(front, key):
    m = re.search(r"^%s:\s*(.+)$" % re.escape(key), front, re.M)
    return m.group(1).strip() if m else ""


def split_note(text):
    """拆成 (frontmatter 文本, 生成区文本, 区外尾巴)。缺标记时尾巴=frontmatter 之后全部内容。"""
    front = ""
    body = text
    if text.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n", text, re.S)
        if m:
            front = m.group(0)
            body = text[m.end():]
    if START in body and END in body:
        i = body.index(START)
        j = body.index(END) + len(END)
        return front, body[i:j], body[j:]
    return front, "", body


def write_note(path, front, inner, tail, dry_run=False):
    """规范化写出：front + 空行 + 生成区 + 空行 + 尾部（缺省补一行备注标题）。

    尾部按 strip("\\n") 归一，保证「同日同输入重跑」逐字节一致。
    """
    tail = (tail or "").strip("\n")
    if not tail:
        tail = "## 备注（手写区，重跑不覆盖）"
    text = front + "\n" + inner + "\n\n" + tail + "\n"
    if dry_run:
        return text
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return text


def existing_tail(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        _, _, tail = split_note(f.read())
    return tail


# ---------------------------------------------------------------- 工作区读取

def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError("空文件：%s" % path)
    header = [h.strip() for h in rows[0]]
    data = [r for r in rows[1:] if any(c.strip() for c in r)]
    missing = [c for c in CORE if c not in header]
    if missing:
        raise ValueError("%s 缺核心列：%s" % (path, "、".join(missing)))
    return header, data


def cell(row, header, name):
    if name not in header:
        return ""
    i = header.index(name)
    return row[i].strip() if len(row) > i else ""


def md_cell(text, limit=40):
    s = (text or "").replace("|", "\\|").replace("\n", " ").strip()
    if len(s) > limit:
        s = s[:limit] + "…"
    return s or "—"


def workspace_path(ws):
    ws = os.path.abspath(ws)
    if not os.path.isdir(ws):
        raise ValueError("工作区不存在：%s" % ws)
    return ws


def exam_of(args, ws):
    """考试标识：--exam 优先，缺省取工作区目录名（与 export_anki.py 的 --exam-id 同口径）。"""
    e = (getattr(args, "exam", None) or "").strip()
    return e or (os.path.basename(ws.rstrip("/\\")) or "exam")


def rel_to_home(ws):
    home = prep_home()
    rel = os.path.relpath(ws, home)
    return rel.replace(os.sep, "/")


# ---------------------------------------------------------------- 笔记内容

def render_errors_body(topic, rows, header):
    cpkg = {}
    conf = {}
    lucky = 0
    anki_due = 0
    anki_relearn = 0
    sources = []
    table = []
    for r in rows:
        e = cell(r, header, "错因(CPKG)") or "无"
        c = cell(r, header, "信心") or "未标"
        cpkg[e] = cpkg.get(e, 0) + 1
        conf[c] = conf.get(c, 0) + 1
        chain = cell(r, header, "推理链")
        if cell(r, header, "对错") == "对" and chain == "不成立":
            lucky += 1
        anki = cell(r, header, "anki状态")
        if anki == "未过":
            anki_due += 1
        elif anki == "重学":
            anki_relearn += 1
        src = cell(r, header, "溯源")
        if src and src not in sources:
            sources.append(src)
        q = cell(r, header, "题目") or cell(r, header, "题干") or cell(r, header, "问题")
        table.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            md_cell(cell(r, header, "date"), 10), md_cell(cell(r, header, "题型"), 4),
            md_cell(c, 4), md_cell(e, 2), md_cell(chain or "未写", 4),
            md_cell(src, 28), md_cell(q)))

    lines = [START + " kind=errors %%", "## 漏洞概览", ""]
    lines.append("- 错题：%d 条" % len(rows))
    lines.append("- 错因分布：%s" % " / ".join("%s %d" % (k, cpkg[k]) for k in sorted(cpkg)))
    lines.append("- 信心分布：%s" % " / ".join("%s %d" % (k, conf[k]) for k in sorted(conf)))
    if lucky:
        lines.append("- 疑似蒙对：%d 条（答案对但推理链不成立 → 不计入掌握度分子）" % lucky)
    if anki_due or anki_relearn:
        lines.append("- Anki 调度：到期未过 %d 条 / 重新学习 %d 条" % (anki_due, anki_relearn))
    lines += ["", "## 错题条目", "",
              "| 日期 | 题型 | 信心 | 错因 | 推理链 | 溯源 | 题目 |",
              "|---|---|---|---|---|---|---|"]
    lines += table
    lines += ["", "## 变式要求", ""]
    if cpkg.get("K"):
        lines.append("- K 类（疑似概念漏洞）：变式题必须写出解题步骤，不能只选答案")
    if cpkg.get("C"):
        lines.append("- C 类（概念性）：先回到材料对应位置重读，再出同类变式")
    if cpkg.get("P"):
        lines.append("- P 类（程序性）：保留同一方法，只更换执行细节，连做 3 道")
    if cpkg.get("G"):
        lines.append("- G 类（覆盖缺口）：先排进本周学习计划，再出基础题")
    if lucky:
        lines.append("- 疑似蒙对：变式题必须写出完整推理链，答案对但链不成立仍按错计")
    if len(lines) and lines[-1] == "":
        lines.append("- （本周无特殊要求）")
    lines += ["", END]
    return "\n".join(lines)


def collect_links(source_values):
    links = []
    for v in source_values:
        for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", v):
            links.append(m.group(1).strip())
    return links


def vault_index(vault):
    names = set()
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d != ".obsidian"]
        for fn in files:
            if fn.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, fn), vault).replace(os.sep, "/")
                names.add(rel[:-3])
                names.add(os.path.basename(rel)[:-3])
    return names


# ---------------------------------------------------------------- 子命令

def cmd_bind(args):
    vault = os.path.abspath(os.path.expanduser(args.vault))
    if not os.path.isdir(vault):
        fail("vault 不存在：%s" % vault)
        return 2
    if not os.path.isdir(os.path.join(vault, ".obsidian")):
        fail("%s 下没有 .obsidian/ 目录，不像是 Obsidian vault；请给出 vault 根目录" % vault)
        return 2
    cfg = {
        "version": 1,
        "enabled": True,
        "vault_path": vault,
        "write_dir": args.write_dir,
        "readonly_sources": args.source or [],
        "deny": args.deny or [],
        "bound_at": args.date or datetime.date.today().isoformat(),
    }
    path = config_path()
    out("vault：%s" % vault)
    out("写入区：%s" % os.path.join(vault, args.write_dir, ""))
    out("只读源：%s" % ("、".join(cfg["readonly_sources"]) or "（未声明；出题只从工作区和会话粘贴取材料）"))
    out("用户主权区：%s" % ("、".join(cfg["deny"]) or "（未声明；写入区之外一律不读写）"))
    if args.dry_run:
        out("（--dry-run：未写入 %s）" % path)
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    out("已绑定 → %s" % path)
    return 0


def cmd_doctor(args):
    cfg = load_config()
    if cfg is None:
        out("未绑定 Obsidian（配置不存在：%s）——这是合法状态，全部功能照常可用。" % config_path())
        return 3
    ws = None
    if getattr(args, "workspace", None):
        try:
            ws = workspace_path(args.workspace)
        except ValueError as e:
            fail(str(e))
            return 2
    wd, code = resolve_write_dir(cfg, ws, getattr(args, "write_dir", None))
    if wd is None:
        out("本工作区的 obsidian_write_dir 为空 —— 本次考试不做 Obsidian 同步（这是你建库时的选择）。")
        return 3
    problem_wd = write_dir_problem(cfg, wd)
    if problem_wd:
        fail(problem_wd)
        return 2
    vault, write_root = vault_paths(cfg, wd)
    problems = []
    if not cfg.get("enabled", True):
        problems.append("配置存在但 enabled=false：同步会被跳过")
    if not os.path.isdir(vault):
        problems.append("vault 不存在：%s" % vault)
    elif not os.path.isdir(os.path.join(vault, ".obsidian")):
        problems.append("vault 缺 .obsidian/：%s" % vault)
    if not os.path.isdir(write_root):
        if args.fix:
            os.makedirs(write_root, exist_ok=True)
            out("已创建写入区：%s" % write_root)
        else:
            # 首次 push 会自动建目录，所以「尚未创建」是提示不是问题，不该让自检变红
            out("写入区尚未创建（首次 push 会自动建，或加 --fix 现在建）：%s" % write_root)
    elif not os.access(write_root, os.W_OK):
        problems.append("写入区不可写：%s" % write_root)
    expected_root = os.path.realpath(os.path.join(vault, wd))
    if write_root != expected_root:
        problems.append("写入区经符号链接解析后与声明路径不一致：%s ≠ %s" % (write_root, expected_root))
    for root, dirs, files in os.walk(write_root):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                problems.append("无法读取 %s：%s" % (p, e))
                continue
            if not text.startswith("---\n"):
                problems.append("缺 frontmatter：%s" % p)
            elif not re.match(r"^---\n.*?\n---\n", text, re.S):
                problems.append("frontmatter 未闭合：%s" % p)
    out("vault：%s" % vault)
    out("写入区：%s" % write_root)
    out("只读源：%s" % ("、".join(cfg.get("readonly_sources") or []) or "（未声明）"))
    if problems:
        for p in problems:
            out("  [问题] %s" % p)
        return 1
    out("PASS：配置、写入区、既有笔记 frontmatter 均正常")
    return 0


def _require_cfg():
    """返回 (cfg, 退出码)：未绑定 → (None, 3)；可用 → (cfg, 0)。

    写入区是否合法由 resolve_write_dir + write_dir_problem 逐次判定（局部路径优先，
    所以全局 write_dir 配错不该拖累一个配对了局部路径的工作区）。
    """
    cfg = load_config()
    if cfg is None or not cfg.get("enabled", True):
        out("未启用 Obsidian 集成（无配置或 enabled=false）——跳过同步，工作区不受影响。")
        return None, 3
    return cfg, 0


def cmd_push_errors(args):
    cfg, code = _require_cfg()
    if cfg is None:
        return code
    try:
        ws = workspace_path(args.workspace)
    except ValueError as e:
        fail(str(e))
        return 2
    args.exam = exam_of(args, ws)
    try:
        header, data = read_csv(os.path.join(ws, "answer_log.csv"))
    except (ValueError, OSError) as e:
        fail(str(e))
        return 2
    wd, code = resolve_write_dir(cfg, ws, args.write_dir)
    if wd is None:
        out("本工作区 obsidian_write_dir 为空 —— 跳过 Obsidian 同步（工作区不受影响）。")
        return 3
    problem_wd = write_dir_problem(cfg, wd)
    if problem_wd:
        fail(problem_wd)
        return 2
    vault, write_root = vault_paths(cfg, wd)
    groups = {}
    for r in data:
        if cell(r, header, "对错") != "错":
            continue
        groups.setdefault(cell(r, header, "模块"), []).append(r)
    if not groups:
        out("工作区没有错题行，未生成笔记。")
        return 0
    existing = {}
    err_dir = os.path.join(write_root, "errors", args.exam)
    if os.path.isdir(err_dir):
        for fn in os.listdir(err_dir):
            if fn.endswith(".md"):
                with open(os.path.join(err_dir, fn), "r", encoding="utf-8") as f:
                    existing[fn[:-3]] = fm_get(f.read(), "topic")
    index = vault_index(vault)
    written = 0
    for topic in sorted(groups):
        rows = groups[topic]
        slug = slugify(topic)
        if slug in existing and existing[slug].strip('"') not in (topic, '"%s"' % topic):
            slug = "%s-%s" % (slug, hashlib.sha256(topic.encode("utf-8")).hexdigest()[:6])
        rel = "errors/%s/%s.md" % (args.exam, slug)
        try:
            target = safe_target(write_root, rel)
        except ValueError as e:
            fail(str(e))
            return 1
        sources = []
        for r in rows:
            s = cell(r, header, "溯源")
            if s and s not in sources:
                sources.append(s)
        cpkg = sorted({cell(r, header, "错因(CPKG)") or "无" for r in rows})
        conf = sorted({cell(r, header, "信心") or "未标" for r in rows})
        anki_due = any(cell(r, header, "anki状态") == "未过" for r in rows)
        anki_relearn = any(cell(r, header, "anki状态") == "重学" for r in rows)
        front = render_frontmatter([
            ("type", "exam_error"),
            ("exam", args.exam),
            ("topic", topic),
            ("cpkg_type", cpkg),
            ("confidence", conf),
            ("source", sources),
            ("workdir_ref", rel_to_home(ws) + "/answer_log.csv"),
            ("holdout", False),
            ("anki_due", anki_due),
            ("anki_relearn", anki_relearn),
            ("generated_at", args.date or datetime.date.today().isoformat()),
            ("tags", ["exam-prep", args.exam]),
        ])
        for link in collect_links(sources):
            if link not in index:
                warn("笔记「%s」的 source 双链无法解析：[[%s]]（在 vault 里找不到该笔记）" % (topic, link))
        body = render_errors_body(topic, rows, header)
        tail = existing_tail(target)
        write_note(target, front, body, tail, dry_run=args.dry_run)
        written += 1
        out("%s %s（%d 条错题）" % ("[dry-run]" if args.dry_run else "已写", rel, len(rows)))
    out("合计 %d 条错题笔记；源：%s" % (written, os.path.join(ws, "answer_log.csv")))
    return 0


def cmd_push_concept(args):
    cfg, code = _require_cfg()
    if cfg is None:
        return code
    try:
        ws = workspace_path(args.workspace)
        with open(args.from_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except (ValueError, OSError) as e:
        fail(str(e))
        return 2
    args.exam = exam_of(args, ws)
    wd, code = resolve_write_dir(cfg, ws, args.write_dir)
    if wd is None:
        out("本工作区 obsidian_write_dir 为空 —— 跳过 Obsidian 同步（工作区不受影响）。")
        return 3
    problem_wd = write_dir_problem(cfg, wd)
    if problem_wd:
        fail(problem_wd)
        return 2
    vault, write_root = vault_paths(cfg, wd)
    mastery = ""
    syl = os.path.join(ws, "syllabus_table.csv")
    if os.path.isfile(syl):
        with open(syl, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        if rows:
            h = [c.strip() for c in rows[0]]
            if "模块" in h and "我的掌握度" in h:
                for r in rows[1:]:
                    if len(r) > max(h.index("模块"), h.index("我的掌握度")) \
                            and r[h.index("模块")].strip() == args.module:
                        mastery = r[h.index("我的掌握度")].strip()
                        break
    linked = []
    err_dir = os.path.join(write_root, "errors", args.exam)
    if os.path.isdir(err_dir):
        for fn in sorted(os.listdir(err_dir)):
            if not fn.endswith(".md"):
                continue
            with open(os.path.join(err_dir, fn), "r", encoding="utf-8") as f:
                topic = fm_get(f.read(), "topic").strip('"')
            if topic and (args.module in topic or topic in args.module):
                linked.append("[[%s/errors/%s/%s]]" % (wd, args.exam, fn[:-3]))
    rel = "concepts/%s/%s.md" % (args.exam, slugify(args.module))
    try:
        target = safe_target(write_root, rel)
    except ValueError as e:
        fail(str(e))
        return 1
    front = render_frontmatter([
        ("type", "exam_concept"),
        ("exam", args.exam),
        ("syllabus_module", args.module),
        ("mastery_at_creation", mastery or None),
        ("linked_errors", linked),
        ("source", args.source or ["[AI 补充]"]),
        ("workdir_ref", rel_to_home(ws) + "/syllabus_table.csv"),
        ("generated_at", args.date or datetime.date.today().isoformat()),
        ("tags", ["exam-prep", args.exam, "concept"]),
    ])
    body = "%s kind=concept %%\n%s\n\n%s" % (START, content, END)
    write_note(target, front, body, existing_tail(target), dry_run=args.dry_run)
    out("%s %s（模块 %s，掌握度 %s）" % ("[dry-run]" if args.dry_run else "已写",
                                        rel, args.module, mastery or "未填"))
    return 0


def cmd_push_review(args):
    cfg, code = _require_cfg()
    if cfg is None:
        return code
    try:
        ws = workspace_path(args.workspace)
        with open(args.report, "r", encoding="utf-8") as f:
            report = f.read().rstrip("\n")
    except (ValueError, OSError) as e:
        fail(str(e))
        return 2
    args.exam = exam_of(args, ws)
    wd, code = resolve_write_dir(cfg, ws, args.write_dir)
    if wd is None:
        out("本工作区 obsidian_write_dir 为空 —— 跳过 Obsidian 同步（工作区不受影响）。")
        return 3
    problem_wd = write_dir_problem(cfg, wd)
    if problem_wd:
        fail(problem_wd)
        return 2
    vault, write_root = vault_paths(cfg, wd)
    gap = ""
    if args.gap_diff:
        try:
            with open(args.gap_diff, "r", encoding="utf-8") as f:
                gap = f.read().rstrip("\n")
        except OSError as e:
            fail("缺口变化文件无法读取：%s" % e)
            return 2
    rel = "reviews/%s/%s.md" % (args.exam, slugify(args.week))
    try:
        target = safe_target(write_root, rel)
    except ValueError as e:
        fail(str(e))
        return 1
    front = render_frontmatter([
        ("type", "exam_review"),
        ("exam", args.exam),
        ("week", args.week),
        ("source", None),
        ("workdir_ref", rel_to_home(ws)),
        ("generated_at", args.date or datetime.date.today().isoformat()),
        ("tags", ["exam-prep", args.exam, "review"]),
    ])
    lines = [START + " kind=review %%", "## 当周周报（原文，未重算）", "", "```text", report, "```", ""]
    lines.append("## 缺口变化（摘自 gap_matrix，未重算）")
    lines.append("")
    lines.append(gap if gap else "（本次未提供 --gap-diff；周报数字以上方原文为准）")
    lines.append("")
    lines.append(END)
    body = "\n".join(lines)
    write_note(target, front, body, existing_tail(target), dry_run=args.dry_run)
    out("%s %s（周 %s）" % ("[dry-run]" if args.dry_run else "已写", rel, args.week))
    return 0


def cmd_check(args):
    cfg = load_config()
    if cfg is None or not cfg.get("enabled", True):
        out("未启用 Obsidian 集成——无笔记可核对。")
        return 3
    try:
        ws = workspace_path(args.workspace)
    except ValueError as e:
        fail(str(e))
        return 2
    args.exam = exam_of(args, ws)
    try:
        header, data = read_csv(os.path.join(ws, "answer_log.csv"))
    except (ValueError, OSError) as e:
        fail(str(e))
        return 2
    wd, code = resolve_write_dir(cfg, ws, args.write_dir)
    if wd is None:
        out("本工作区 obsidian_write_dir 为空 —— 没有需要核对的笔记。")
        return 3
    problem_wd = write_dir_problem(cfg, wd)
    if problem_wd:
        fail(problem_wd)
        return 2
    vault, write_root = vault_paths(cfg, wd)
    counts = {}
    for r in data:
        if cell(r, header, "对错") == "错":
            t = cell(r, header, "模块")
            counts[t] = counts.get(t, 0) + 1
    err_dir = os.path.join(write_root, "errors", args.exam)
    bad = 0
    if os.path.isdir(err_dir):
        for fn in sorted(os.listdir(err_dir)):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(err_dir, fn)
            with open(p, "r", encoding="utf-8") as f:
                text = f.read()
            topic = fm_get(text, "topic").strip('"')
            n_rows = len(re.findall(r"^\| \d{4}-\d{2}-\d{2} ", text, re.M))
            expected = counts.get(topic, 0)
            flag = "PASS" if n_rows == expected else "MISMATCH"
            if flag == "MISMATCH":
                bad += 1
            out("%-8s %s：笔记 %d 条 / 日志 %d 条" % (flag, fn, n_rows, expected))
    else:
        out("（尚无错题笔记：%s）" % err_dir)
    if bad:
        out("发现 %d 处不一致——笔记是派生视图，重跑 push-errors 以日志为准覆盖生成区。" % bad)
        return 1
    out("PASS：笔记条目数与 answer_log 一致")
    return 0


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        description="exam-prep → Obsidian 单向派生写入（六文件工作区始终是权威）")
    sub = p.add_subparsers(dest="cmd")

    b = sub.add_parser("bind", help="绑定 vault（写 EXAM_PREP_HOME/obsidian_config.json）")
    b.add_argument("--vault", required=True)
    b.add_argument("--write-dir", default=DEFAULT_WRITE_DIR)
    b.add_argument("--source", action="append", help="只读源材料目录（可重复）")
    b.add_argument("--deny", action="append", help="用户主权区（可重复，永不读写）")
    b.add_argument("--date", default=None, help="绑定日期（默认今天，YYYY-MM-DD）")
    b.add_argument("--dry-run", action="store_true")
    b.set_defaults(func=cmd_bind)

    d = sub.add_parser("doctor", help="自检：vault/写入区/frontmatter/符号链接")
    d.add_argument("--fix", action="store_true", help="自动创建缺失的写入区")
    d.add_argument("--workspace", default=None, help="指定后按该工作区的局部 obsidian_write_dir 自检")
    d.add_argument("--write-dir", default=None, help="临时覆盖写入区（相对 vault）")
    d.set_defaults(func=cmd_doctor)

    e = sub.add_parser("push-errors", help="按 topic 聚合推送错题笔记")
    e.add_argument("--workspace", required=True)
    e.add_argument("--exam", default=None, help="考试标识（缺省取 --workspace 的目录名）")
    e.add_argument("--write-dir", default=None,
                   help="vault 内的写入子目录；缺省读 <工作区>/learner_profile.json 的 obsidian_write_dir")
    e.add_argument("--date", default=None)
    e.add_argument("--dry-run", action="store_true")
    e.set_defaults(func=cmd_push_errors)

    c = sub.add_parser("push-concept", help="推送一条概念笔记（内容由会话中的讲授步骤产出）")
    c.add_argument("--workspace", required=True)
    c.add_argument("--exam", default=None, help="考试标识（缺省取 --workspace 的目录名）")
    c.add_argument("--write-dir", default=None,
                   help="vault 内的写入子目录；缺省读 <工作区>/learner_profile.json 的 obsidian_write_dir")
    c.add_argument("--module", required=True)
    c.add_argument("--from", dest="from_file", required=True, help="讲授正文文件（场景/三块/标准表述/自测）")
    c.add_argument("--source", action="append", help="溯源标签（可重复；缺省 [AI 补充]）")
    c.add_argument("--date", default=None)
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_push_concept)

    r = sub.add_parser("push-review", help="推送一条周复盘笔记（嵌入周报原文，不重算）")
    r.add_argument("--workspace", required=True)
    r.add_argument("--exam", default=None, help="考试标识（缺省取 --workspace 的目录名）")
    r.add_argument("--write-dir", default=None,
                   help="vault 内的写入子目录；缺省读 <工作区>/learner_profile.json 的 obsidian_write_dir")
    r.add_argument("--week", required=True, help="如 2026-W45")
    r.add_argument("--report", required=True, help="weekly_report.py 的输出文件")
    r.add_argument("--gap-diff", default=None, help="gap_matrix 变化摘要（可选）")
    r.add_argument("--date", default=None)
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_push_review)

    k = sub.add_parser("check", help="只读核对：笔记条目数 vs answer_log")
    k.add_argument("--workspace", required=True)
    k.add_argument("--exam", default=None, help="考试标识（缺省取 --workspace 的目录名）")
    k.add_argument("--write-dir", default=None,
                   help="vault 内的写入子目录；缺省读 <工作区>/learner_profile.json 的 obsidian_write_dir")
    k.set_defaults(func=cmd_check)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
