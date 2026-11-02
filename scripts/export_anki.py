#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_anki.py —— 从 answer_log.csv 错题行导出 Anki 可导入 CSV（plan 5.6 / D-9 / AC-24）。

输出契约（逐字）：三列表头 `Front,Back,Tags`；UTF-8 无 BOM；首行表头；
Tags 空格分隔：`<考试标识> <知识点> <错因代码>`（如 `sample-demo 遗传 K`）；
日志含附加列「来源」（习题课/作业/真题等，外部题目录入约定）时追加第四段来源标签。
仅生成文件，无任何 Anki 运行时依赖（无 Anki 环境照常验收，AC-24）。

Front/Back 内容口径：answer_log.csv 核心契约不含题面文本。若日志含附加列
「题目」（或「题干」/「问题」）与「答案」（或「正确答案」），优先采用原文；
否则用确定性模板占位（Front=模块+题型+日期的重做提示，Back=错因/信心/溯源指引），
并把占位这一事实打印在 stdout——占位卡片用于错题索引，完整题面请在 Anki 中补齐。
Tags 中若考试标识/知识点含空格，替换为下划线（Anki 以空格分隔标签）。
留出集行（「是否留出集」=是）不导出——重测前不得进日常调度（measurement_guide.md 附录），
导出时在 stdout 报告跳过条数。写出的单元格若以 = / + / - / @ 开头（Excel 公式注入前缀），
写出时前置单引号中和（Excel 侧按文本处理，Anki 导入仅多一个前导符）。

v1.5 回填模式（`--import-due <清单.csv> [--dry-run]`）：把 Anki「到期未过 / 重新学习」清单
写回 answer_log 的附加列 `anki状态`（∈ {未过,重学}）。清单至少含 `date,模块` 两列，
可选 `anki状态`/`状态`/`state` 列（缺省按「未过」）。纪律：只填空白、永不覆盖已有值、
只动这一列、留出集行跳过、同键多行取最后一行并报「多义」。该列是 mastery_calc 折扣的输入；
这是本技能对 append-only 的唯一窄例外，细节见 references/anki_scheduling.md。

【Python 不可用时的降级说明】（AC-21）
PowerShell 等价（生成三列错题 CSV）：
  $w = Import-Csv answer_log.csv | Where-Object { $_.'对错' -eq '错' }
  'Front,Back,Tags' | Set-Content -Encoding utf8 anki_export.csv   # 注意：PS5 的 utf8 恒带 BOM，
  $w | ForEach-Object { '"{0}","{1}","{2}"' -f "<题面占位>", ("错因:"+$_.'错因(CPKG)'), ("考试标识 "+$_.'模块'+" "+$_.'错因(CPKG)') } |
    Add-Content -Encoding utf8 anki_export.csv
手动检查要点：表头 Front,Back,Tags 逐字；保存为 UTF-8（无 BOM 最佳，带 BOM 时 Anki
新版本可导入但首列名会带 BOM 前缀）；Tags 三段以空格分隔；脚本版还会跳过留出集行、
并把 =/+/-/@ 开头的单元格前置单引号中和（手工路径可自行在 Where-Object 加
`$_.'是否留出集' -ne '是'` 过滤）。
"""
import argparse
import csv
import os
import sys

QUESTION_KEYS = ["题目", "题干", "问题"]
ANSWER_KEYS = ["答案", "正确答案", "标准答案"]
ANKI_COL = "anki状态"
ANKI_STATES = ("未过", "重学")


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def import_due(args):
    """v1.5 回填模式：把 Anki「到期未过 / 重新学习」清单写进 answer_log 的 anki状态 列。

    纪律（真源：references/anki_scheduling.md）：
    - 只填空白单元格，永不覆盖已有值；
    - 只动 anki状态 这一列，其他单元格解析后逐格不变（CSV 语义等价，引号可能被规范化）；
    - 匹配键 = (date, 模块)；同一键多行候选时取日志中最后一行，并报「多义」条数；
    - 「是否留出集=是」的行一律跳过——留出集不进 Anki 调度。
    """
    ws = args.workspace.rstrip("/\\")
    log_path = ws + "/answer_log.csv"
    try:
        with open(log_path, "rb") as f:
            had_bom = f.read(3) == b"\xef\xbb\xbf"
    except OSError as e:
        sys.stderr.write("FAIL: 无法读取 %s：%s\n" % (log_path, e))
        return 1
    try:
        rows = _read_csv(log_path)
        due = _read_csv(args.import_due)
    except UnicodeDecodeError:
        sys.stderr.write("FAIL: 输入不是 UTF-8，请另存为 UTF-8 后重试\n")
        return 1
    except OSError as e:
        sys.stderr.write("FAIL: 无法读取输入：%s\n" % e)
        return 1
    if not rows:
        sys.stderr.write("FAIL: %s 为空\n" % log_path)
        return 1

    header = [h.strip() for h in rows[0]]
    core = ["date", "模块", "题型", "对错", "信心", "错因(CPKG)", "是否留出集"]
    missing = [c for c in core if c not in header]
    if missing:
        sys.stderr.write("FAIL: %s 缺核心列：%s（先跑 validate_log.py）\n"
                         % (log_path, "、".join(missing)))
        return 1
    added_col = False
    if ANKI_COL not in header:
        header.append(ANKI_COL)
        rows = [header] + [r + [""] * (len(header) - len(r)) for r in rows[1:]]
        added_col = True
    idx = {name: header.index(name) for name in header}

    if not due:
        sys.stderr.write("FAIL: 清单为空：%s\n" % args.import_due)
        return 1
    dh = [h.strip() for h in due[0]]
    lacking = [c for c in ("date", "模块") if c not in dh]
    if lacking:
        sys.stderr.write("FAIL: 清单缺列：%s（至少需要 date,模块；可选 anki状态）\n"
                         % "、".join(lacking))
        return 2
    i_d_date, i_d_mod = dh.index("date"), dh.index("模块")
    i_d_state = next((dh.index(c) for c in (ANKI_COL, "状态", "state") if c in dh), None)

    # 日志侧索引：键 (date, 模块) → 行号列表（保持文件顺序，append-only ⇒ 时间序）
    index = {}
    for n, r in enumerate(rows[1:], start=3):  # 行号按表头占第 1 行粗算
        if len(r) != len(header) or all(not c.strip() for c in r):
            continue
        key = (r[idx["date"]].strip(), r[idx["模块"]].strip())
        index.setdefault(key, []).append(n - 3)

    filled, skipped_filled, skipped_holdout = 0, 0, 0
    ambiguous, unmatched, invalid_state = [], [], []
    touched = []
    for drow in due[1:]:
        if not drow or all(not c.strip() for c in drow):
            continue
        date = drow[i_d_date].strip() if len(drow) > i_d_date else ""
        mod = drow[i_d_mod].strip() if len(drow) > i_d_mod else ""
        state = (drow[i_d_state].strip() if (i_d_state is not None and len(drow) > i_d_state) else "")
        if not state:
            state = "未过"
        elif state not in ANKI_STATES:
            invalid_state.append("%s %s=%s" % (date, mod, state))
            continue
        cands = index.get((date, mod), [])
        if not cands:
            unmatched.append("%s %s" % (date, mod))
            continue
        if len(cands) > 1:
            ambiguous.append("%s %s（%d 行，取最后一行）" % (date, mod, len(cands)))
        ri = cands[-1]
        row = rows[ri + 1]
        if row[idx["是否留出集"]].strip() == "是":
            skipped_holdout += 1
            continue
        if row[idx[ANKI_COL]].strip():
            skipped_filled += 1
            continue
        row[idx[ANKI_COL]] = state
        filled += 1
        touched.append("%s %s → %s" % (date, mod, state))

    if not args.dry_run and (filled or added_col):
        with open(log_path, "w", encoding="utf-8-sig" if had_bom else "utf-8", newline="") as f:
            csv.writer(f).writerows(rows)
    for line in touched[:20]:
        sys.stdout.write("  回填 %s\n" % line)
    if len(touched) > 20:
        sys.stdout.write("  …（另有 %d 条，略）\n" % (len(touched) - 20))
    sys.stdout.write("%s回填 %d 行；跳过（已有值）%d 行；跳过（留出集）%d 行；"
                     "多义 %d 处；未匹配 %d 条；状态非法 %d 条%s\n"
                     % ("[dry-run] " if args.dry_run else "", filled, skipped_filled,
                        skipped_holdout, len(ambiguous), len(unmatched), len(invalid_state),
                        "；已新增列 anki状态" if added_col else ""))
    for tag, items in (("多义", ambiguous), ("未匹配", unmatched), ("状态非法", invalid_state)):
        for it in items[:5]:
            sys.stderr.write("WARN[%s] %s\n" % (tag, it))
    if args.dry_run:
        sys.stdout.write("（--dry-run：未写入 %s）\n" % log_path)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="错题导出 Anki CSV（Front,Back,Tags 三列，UTF-8 无 BOM）")
    parser.add_argument("workspace", nargs="?", default=".",
                        help="考试工作区目录（默认当前目录）")
    parser.add_argument("--out", default=None,
                        help="输出 CSV 路径（默认 <workspace>/anki_export.csv）")
    parser.add_argument("--exam-id", default=None,
                        help="考试标识（默认取 workspace 目录名）")
    parser.add_argument("--import-due", default=None, metavar="CSV",
                        help="v1.5 回填模式：读取 Anki 到期未过/重新学习清单（含 date,模块 两列，"
                             "可选 anki状态 列=未过/重学，缺省按未过），只填 answer_log 的空单元格")
    parser.add_argument("--dry-run", action="store_true",
                        help="回填模式：只打印将要回填的行，不写文件")
    args = parser.parse_args(argv)
    if args.import_due:
        return import_due(args)

    ws = args.workspace.rstrip("/\\")
    log_path = ws + "/answer_log.csv"
    out_path = args.out if args.out else ws + "/anki_export.csv"
    exam_id = args.exam_id if args.exam_id else (os.path.basename(ws) if ws not in ("", ".") else "exam")

    try:
        with open(log_path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    except UnicodeDecodeError as e:
        sys.stderr.write("FAIL: 文件 %s 不是 UTF-8 编码（无效字节 0x%02x 于偏移 %d）。"
                         "检测到非 UTF-8 编码，请用编辑器另存为 UTF-8 后重试；"
                         "Excel/WPS 用户请选「CSV UTF-8」格式保存\n"
                         % (log_path, e.object[e.start] if e.object else 0, e.start))
        return 1
    except OSError as e:
        sys.stderr.write("FAIL: 无法读取 %s：%s\n" % (log_path, e))
        return 1
    if not rows:
        sys.stderr.write("FAIL: %s 为空\n" % log_path)
        return 1
    header = [h.strip() for h in rows[0]]
    core = ["date", "模块", "题型", "对错", "信心", "错因(CPKG)", "是否留出集"]
    missing = [c for c in core if c not in header]
    if missing:
        sys.stderr.write("FAIL: %s 缺核心列：%s（先跑 validate_log.py）\n" % (log_path, "、".join(missing)))
        return 1
    idx = {name: header.index(name) for name in header}

    def qcol(keys):
        for k in keys:
            if k in idx:
                return k
        return None
    q_key, a_key = qcol(QUESTION_KEYS), qcol(ANSWER_KEYS)
    if q_key is None:
        sys.stdout.write("（日志无「题目」类附加列，Front 用确定性占位模板；"
                         "如需真实题面请在 answer_log.csv 增加附加列「题目」「答案」）\n")

    def tagify(s):
        return s.strip().replace(" ", "_") if s.strip() else "未标"

    def excel_safe(cell):
        """以 =/+/-/@/Tab/CR 开头的单元格前置单引号，防 Excel/WPS 公式注入（安全评审发现 1）。"""
        s = str(cell)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    cards = []
    skipped_misaligned = 0
    skipped_holdout = 0
    for r in rows[1:]:
        if not r or all(not c.strip() for c in r):
            continue
        if len(r) != len(header):
            skipped_misaligned += 1
            continue

        def get(name):
            i = idx[name]
            return r[i].strip() if len(r) > i else ""
        if get("对错") != "错":
            continue
        if get("是否留出集") == "是":
            skipped_holdout += 1
            continue
        mod = get("模块")
        typ = get("题型")
        date = get("date")
        conf = get("信心") or "未标"
        err = get("错因(CPKG)") or "无"
        src = get("来源") if "来源" in idx else ""
        trace = get("溯源") if "溯源" in idx else ""
        if q_key and a_key:
            front, back = get(q_key), get(a_key)
        else:
            front, back = "", ""
        if not front:
            front = "【%s·%s】%s 错题重做：请复述题目并写出完整解题过程" % (mod, typ, date)
        if not back:
            if trace:
                back = "错因：%s｜当时信心：%s｜溯源：%s" % (err, conf, trace)
            else:
                back = "错因：%s｜当时信心：%s｜溯源：%s 的 %s 行" % (err, conf, log_path, date)
        elif trace:
            back = "%s｜溯源：%s" % (back, trace)
        tags = " ".join([tagify(exam_id), tagify(mod), tagify(err)]
                        + ([tagify(src)] if src else []))
        cards.append((front, back, tags))

    n = 0
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["Front", "Back", "Tags"])
        for c in cards:
            w.writerow([excel_safe(x) for x in c])
            n += 1
    if skipped_misaligned:
        sys.stderr.write("WARN: %d 行列数与表头不齐，已跳过（先跑 validate_log.py 定位行号）\n"
                         % skipped_misaligned)
    sys.stdout.write("已导出 %d 张错题卡片 → %s（Front,Back,Tags；UTF-8 无 BOM；考试标识=%s）\n"
                     % (n, out_path, exam_id))
    sys.stdout.write("已跳过 %d 条留出集行（重测前不得进日常调度）\n" % skipped_holdout)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
