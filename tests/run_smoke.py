#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_smoke.py —— exam-prep 技能的自检（纯标准库，不联网，不改本目录任何文件）。

用法：python <skill>/tests/run_smoke.py [-v]
退出码：0 全过；1 有失败。每个用例打印一行 PASS/FAIL，失败附首行诊断。

覆盖：
  T1 validate_log 契约校验（旧日志 / v1.5 日志 / 越界枚举）
  T2 mastery_calc 与蓝本逐字节一致（无 v1.5 列时）
  T3 mastery_calc 的推理链修正与 Anki 折扣（数值对齐文档算例）
  T4 weekly_report 与蓝本一致 + v1.5 三段只在有列时出现
  T5 export_anki 与蓝本逐字节一致（无 溯源 列时）
  T6 export_anki --import-due 只填空、跳过留出集、幂等
  T7 verify_heldout 记录/校验/篡改后 FAIL
  T8 obsidian_sync 绑定、幂等、路径逃逸与符号链接拒绝、无配置降级
  T9 权威边界测试：改笔记不影响任何统计与哈希；重推恢复生成区、保留手写区
  T10 按工作区隔离：局部 obsidian_write_dir 生效、空值静默跳过、缺字段回退全局、不改全局配置
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL, "scripts")
FIX = os.path.join(SKILL, "tests", "fixtures")
GOLD = os.path.join(SKILL, "tests", "golden")
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

FAILS = []
CHECKS = [0]


def run(script, *args, **kw):
    cmd = [sys.executable, os.path.join(SCRIPTS, script)] + [str(a) for a in args]
    env = dict(os.environ)
    env.update(kw.get("env") or {})
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


def check(name, ok, detail=""):
    CHECKS[0] += 1
    if ok:
        print("PASS %s" % name)
        if VERBOSE and detail:
            print("     %s" % detail)
    else:
        print("FAIL %s" % name)
        if detail:
            print("     %s" % detail.replace("\n", "\n     ")[:1200])
        FAILS.append(name)


def norm(text, *paths):
    for p in paths:
        text = text.replace(p, "<WS>")
    return text


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def make_ws(prefix="ws", log="answer_log_core.csv", syllabus=True):
    d = tempfile.mkdtemp(prefix="ep-%s-" % prefix)
    shutil.copy(os.path.join(FIX, log), os.path.join(d, "answer_log.csv"))
    if syllabus:
        shutil.copy(os.path.join(FIX, "syllabus_table.csv"), os.path.join(d, "syllabus_table.csv"))
    return d


# ------------------------------------------------------------------ T1

def t1_validate():
    ws = make_ws("v1")
    r = run("validate_log.py", os.path.join(ws, "answer_log.csv"))
    check("T1.1 旧日志 PASS", r.returncode == 0 and "PASS" in r.stdout,
          r.stdout + r.stderr)
    ws2 = make_ws("v1b", log="answer_log_v15.csv")
    r = run("validate_log.py", os.path.join(ws2, "answer_log.csv"))
    check("T1.2 v1.5 日志 PASS（空 anki状态 不告警）", r.returncode == 0 and "PASS" in r.stdout,
          r.stdout + r.stderr)
    bad = os.path.join(ws, "bad.csv")
    write(bad, "date,模块,题型,对错,信心,错因(CPKG),是否留出集,推理链\n"
               "2026-10-20,甲,客观,对,稳,无,否,乱填\n")
    r = run("validate_log.py", bad)
    check("T1.3 推理链越界 → FAIL 退出 1", r.returncode == 1 and "乱填" in r.stderr,
          r.stdout + r.stderr)


# ------------------------------------------------------------------ T2

def t2_mastery_parity():
    ws = make_ws("m2")
    r = run("mastery_calc.py", ws)   # 不带 --dry-run：金标由蓝本同参数生成
    got = norm(r.stdout, ws)
    want = read(os.path.join(GOLD, "mastery_core.txt"))
    check("T2.1 mastery 输出与蓝本金标逐字节一致", got == want,
          "--- got ---\n%s\n--- want ---\n%s" % (got, want))
    check("T2.2 掌握度数值 = 蓝本 0.53/0.54/0.19",
          "0.53" in got and "0.54" in got and "0.19" in got, got)


# ------------------------------------------------------------------ T3

def t3_mastery_v15():
    ws = make_ws("m3", log="answer_log_v15.csv")
    r = run("mastery_calc.py", ws, "--dry-run")
    out = r.stdout
    check("T3.1 疑似蒙对按错计（分离定律 0.04）", "0.04" in out, out)
    check("T3.2 无 anki 行的模块不折扣（自由组合 0.54）", "0.54" in out, out)
    check("T3.3 anki 折扣生效（连锁交换 0.61 = 0.72×(1−0.15)）", "0.61" in out, out)
    check("T3.4 折扣诊断写 stderr 不进 stdout", "frac_due" in r.stderr and "frac_due" not in out,
          r.stderr)
    r2 = run("mastery_calc.py", ws, "--dry-run", "--ignore-chain")
    check("T3.5 --ignore-chain 关闭链修正（分离定律回升）",
          "0.04" not in r2.stdout and "分离定律" in r2.stdout, r2.stdout)


# ------------------------------------------------------------------ T4

def t4_weekly():
    ws = make_ws("w4")
    r = run("weekly_report.py", ws)
    got = norm(r.stdout, ws)
    want = read(os.path.join(GOLD, "weekly_core.txt"))
    check("T4.1 旧日志周报与蓝本逐字节一致", got == want,
          "--- got ---\n%s\n--- want ---\n%s" % (got, want))
    check("T4.2 无 v1.5 列时三段不出现",
          "疑似蒙对" not in got and "溯源分布" not in got and "Anki 调度回填" not in got, got)
    ws2 = make_ws("w4b", log="answer_log_v15.csv")
    r2 = run("weekly_report.py", ws2)
    o = r2.stdout
    check("T4.3 v1.5 三段出现", "疑似蒙对" in o and "溯源分布" in o and "Anki 调度回填" in o, o)
    check("T4.4 疑似蒙对清单点名模块", "遗传-分离定律" in o.split("疑似蒙对")[1] if "疑似蒙对" in o else False, o)


# ------------------------------------------------------------------ T5

def t5_anki_parity():
    ws = make_ws("a5")
    r = run("export_anki.py", ws, "--exam-id", "demo")
    got = norm(read(os.path.join(ws, "anki_export.csv")), ws)
    want = read(os.path.join(GOLD, "anki_core.csv"))
    check("T5.1 旧日志导出与蓝本逐字节一致", got == want,
          "--- got ---\n%s\n--- want ---\n%s" % (got, want))
    check("T5.2 导出卡数 = 错题行数（4）", got.count("\n") - 1 == 4, got)


# ------------------------------------------------------------------ T6

def t6_import_due():
    d = tempfile.mkdtemp(prefix="ep-a6-")
    write(os.path.join(d, "answer_log.csv"),
          "date,模块,题型,对错,信心,错因(CPKG),是否留出集,溯源\n"
          "2026-10-20,甲,客观,错,稳,K,否,[材料 讲义 p.1]\n"
          "2026-10-21,甲,客观,对,蒙,无,否,[材料 讲义 p.2]\n"
          "2026-10-22,乙,客观,错,稳,C,是,[材料 讲义 p.3]\n")
    write(os.path.join(d, "due.csv"),
          "date,模块,anki状态\n2026-10-20,甲,未过\n2026-10-21,甲,重学\n2026-10-22,乙,未过\n2026-10-30,丙,未过\n")
    before = sha(os.path.join(d, "answer_log.csv"))
    r = run("export_anki.py", d, "--import-due", os.path.join(d, "due.csv"), "--dry-run")
    check("T6.1 --dry-run 不写文件", sha(os.path.join(d, "answer_log.csv")) == before, r.stdout)
    r = run("export_anki.py", d, "--import-due", os.path.join(d, "due.csv"))
    txt = read(os.path.join(d, "answer_log.csv"))
    check("T6.2 新增列并回填 2 行", "anki状态" in txt and "未过" in txt and "重学" in txt, txt)
    check("T6.3 留出集行跳过（该行 anki 为空）",
          txt.strip().splitlines()[3].endswith(","), txt)
    check("T6.4 未匹配清单报 WARN", "丙" in r.stderr and "未匹配" in r.stdout, r.stdout + r.stderr)
    after = sha(os.path.join(d, "answer_log.csv"))
    run("export_anki.py", d, "--import-due", os.path.join(d, "due.csv"))
    check("T6.5 幂等：二次回填不再改动", sha(os.path.join(d, "answer_log.csv")) == after, "")
    write(os.path.join(d, "due2.csv"), "date,模块,anki状态\n2026-10-20,甲,重学\n")
    run("export_anki.py", d, "--import-due", os.path.join(d, "due2.csv"))
    check("T6.6 永不覆盖已有值", "未过" in read(os.path.join(d, "answer_log.csv")), "")


# ------------------------------------------------------------------ T7

def t7_heldout():
    ws = make_ws("h7")
    ho = os.path.join(ws, "held_out.md")
    shutil.copy(os.path.join(FIX, "held_out.md"), ho)
    r = run("verify_heldout.py", "--record", ho)
    check("T7.1 --record 成功并生成 .sha256", r.returncode == 0 and os.path.isfile(ho + ".sha256"),
          r.stdout + r.stderr)
    r = run("verify_heldout.py", "--verify", ho)
    check("T7.2 未改动 → PASS", r.returncode == 0, r.stdout + r.stderr)
    write(ho, read(ho) + "\n## H2 偷偷加的题\n- 答案: C\n")
    r = run("verify_heldout.py", "--verify", ho)
    check("T7.3 篡改 → FAIL 退出 1", r.returncode == 1 and "FAIL" in (r.stdout + r.stderr),
          r.stdout + r.stderr)


# ------------------------------------------------------------------ T8

def t8_obsidian():
    home = tempfile.mkdtemp(prefix="ep-h8-")
    vault = os.path.join(home, "vault")
    os.makedirs(os.path.join(vault, ".obsidian"))
    os.makedirs(os.path.join(vault, "Courses"))
    write(os.path.join(vault, "Courses", "遗传学讲义.md"), "# 遗传学讲义\n\n## 3.2 分离定律\n")
    ws = os.path.join(home, "exams", "demo")
    os.makedirs(ws)
    shutil.copy(os.path.join(FIX, "answer_log_v15.csv"), os.path.join(ws, "answer_log.csv"))
    shutil.copy(os.path.join(FIX, "syllabus_table.csv"), os.path.join(ws, "syllabus_table.csv"))
    env = {"EXAM_PREP_HOME": home}
    r = run("obsidian_sync.py", "push-errors", "--workspace", ws, "--exam", "demo", env=env)
    check("T8.1 未绑定 → 退出 3（静默降级）", r.returncode == 3, r.stdout + r.stderr)
    r = run("obsidian_sync.py", "bind", "--vault", vault, "--date", "2026-11-02", env=env)
    check("T8.2 bind 写配置", r.returncode == 0 and os.path.isfile(os.path.join(home, "obsidian_config.json")),
          r.stdout + r.stderr)
    run("obsidian_sync.py", "doctor", "--fix", env=env)
    r = run("obsidian_sync.py", "push-errors", "--workspace", ws, "--exam", "demo",
            "--date", "2026-11-02", env=env)
    note = os.path.join(vault, "ExamPrep", "errors", "demo", "遗传-分离定律.md")
    check("T8.3 推送生成笔记", r.returncode == 0 and os.path.isfile(note), r.stdout + r.stderr)
    h1 = sha(note)
    run("obsidian_sync.py", "push-errors", "--workspace", ws, "--exam", "demo",
        "--date", "2026-11-02", env=env)
    check("T8.4 同日重推幂等", sha(note) == h1, "")
    r = run("obsidian_sync.py", "push-errors", "--workspace", ws, "--exam", "../../逃",
            "--dry-run", env=env)
    check("T8.5 路径穿越 → 退出 1", r.returncode == 1, r.stdout + r.stderr)
    cfg = os.path.join(home, "obsidian_config.json")
    write(cfg, read(cfg).replace('"write_dir": "ExamPrep"', '"write_dir": "/tmp"'))
    r = run("obsidian_sync.py", "push-errors", "--workspace", ws, "--exam", "demo", "--dry-run", env=env)
    check("T8.6 绝对 write_dir → 退出 2", r.returncode == 2, r.stdout + r.stderr)
    write(cfg, read(cfg).replace('"write_dir": "/tmp"', '"write_dir": "ExamPrep"'))
    r = run("obsidian_sync.py", "check", "--workspace", ws, "--exam", "demo", env=env)
    check("T8.7 check 读出条目数一致", r.returncode == 0 and "PASS" in r.stdout, r.stdout + r.stderr)
    shutil.rmtree(home, ignore_errors=True)


# ------------------------------------------------------------------ T9 权威边界

def t9_authority():
    home = tempfile.mkdtemp(prefix="ep-h9-")
    vault = os.path.join(home, "vault")
    os.makedirs(os.path.join(vault, ".obsidian"))
    ws = os.path.join(home, "exams", "demo")
    os.makedirs(ws)
    # 3 条错 + 1 条「对但推理链不成立」+ 1 条留出集
    write(os.path.join(ws, "answer_log.csv"),
          "date,模块,题型,对错,信心,错因(CPKG),是否留出集,溯源,推理链,anki状态\n"
          "2026-10-20,甲模块,客观,错,稳,K,否,[材料 讲义 p.1],不成立,\n"
          "2026-10-20,甲模块,客观,错,不确定,C,否,[材料 讲义 p.2],成立,未过\n"
          "2026-10-21,乙模块,主观,错,蒙,P,否,[AI 补充],不成立,\n"
          "2026-10-21,乙模块,客观,对,稳,无,否,[材料 讲义 p.5],不成立,\n"
          "2026-10-22,甲模块,客观,对,稳,无,是,[材料 讲义 p.9],成立,\n")
    shutil.copy(os.path.join(FIX, "syllabus_table.csv"), os.path.join(ws, "syllabus_table.csv"))
    ho = os.path.join(ws, "held_out.md")
    shutil.copy(os.path.join(FIX, "held_out.md"), ho)
    run("verify_heldout.py", "--record", ho)
    env = {"EXAM_PREP_HOME": home}
    run("obsidian_sync.py", "bind", "--vault", vault, "--date", "2026-11-02", env=env)
    run("obsidian_sync.py", "doctor", "--fix", env=env)
    run("obsidian_sync.py", "push-errors", "--workspace", ws, "--exam", "demo",
        "--date", "2026-11-02", env=env)

    # 篡改笔记：改 frontmatter、注入手写段、注入留出集双链
    note = os.path.join(vault, "ExamPrep", "errors", "demo", "甲模块.md")
    orig = read(note)
    tampered = (orig.replace("cpkg_type:\n  - K", "cpkg_type:\n  - C")
                    .replace("confidence:\n  - 稳", "confidence:\n  - 蒙")
                    .replace("## 备注", "## 备注\n[[留出集答案]] 我改的 frontmatter 在上面")
                    .replace("| 2026-10-20 | 客观 |", "| 2026-10-20 | 客观（我改的）|"))
    write(note, tampered)
    check("T9.1 笔记已被篡改", read(note) != orig, "")

    # 关键断言：统计与哈希完全不受笔记影响
    h_log = sha(os.path.join(ws, "answer_log.csv"))
    h_syl = sha(os.path.join(ws, "syllabus_table.csv"))
    h_ho = sha(ho)
    r_m = run("mastery_calc.py", ws, "--dry-run")
    r_w = run("weekly_report.py", ws)
    r_v = run("verify_heldout.py", "--verify", ho)
    check("T9.2 只要文件没被改，日志/考点表/留出集哈希不变",
          sha(os.path.join(ws, "answer_log.csv")) == h_log
          and sha(os.path.join(ws, "syllabus_table.csv")) == h_syl
          and sha(ho) == h_ho, "")
    check("T9.3 掌握度不读笔记（非法写入无影响：甲模块 base 0.39 → 折扣 0.37）",
          r_m.returncode == 0 and "0.37" in r_m.stdout and "base=0.39" in r_m.stderr,
          r_m.stdout + r_m.stderr)
    check("T9.4 周报不读笔记", r_w.returncode == 0 and "疑似蒙对" in r_w.stdout, r_w.stdout)
    check("T9.5 留出集哈希校验仍 PASS", r_v.returncode == 0, r_v.stdout + r_v.stderr)

    # 重推：生成区恢复、手写区保留、注入的双链被丢弃（它在生成区外但属于 frontmatter/生成区之间？
    # 按设计：## 备注 是手写区 → 保留；生成区内的篡改 → 覆盖）
    run("obsidian_sync.py", "push-errors", "--workspace", ws, "--exam", "demo",
        "--date", "2026-11-02", env=env)
    now = read(note)
    check("T9.6 生成区被日志覆盖（我改的表格单元格消失）", "我改的）" not in now, now)
    fm = now.split("\n---\n")[0]
    check("T9.7 frontmatter 由日志重算（含日志里有的 C/K，不含被篡改塞入的「蒙」）",
          "- K" in fm and "- C" in fm and "- 蒙" not in fm and "- 稳" in fm, fm)
    check("T9.8 手写区保留（含用户注入的双链）",
          "[[留出集答案]] 我改的 frontmatter 在上面" in now, now)
    check("T9.9 统计仍未变", sha(os.path.join(ws, "answer_log.csv")) == h_log, "")

    # 导出与 check
    r = run("export_anki.py", ws, "--exam-id", "demo")
    cards = read(os.path.join(ws, "anki_export.csv"))
    n_cards = cards.count("\n") - 1
    r2 = run("obsidian_sync.py", "check", "--workspace", ws, "--exam", "demo", env=env)
    check("T9.10 导出卡数 = 错题行数（3，留出集与答对行不导出）", n_cards == 3, cards)
    check("T9.11 check 只读且一致", r2.returncode == 0, r2.stdout + r2.stderr)
    check("T9.12 导出内容不含留出集线索",
          "留出集" not in cards and "p.9" not in cards, cards)
    shutil.rmtree(home, ignore_errors=True)


# ------------------------------------------------------------------ T10 按工作区隔离

def t10_workspace_isolation():
    home = tempfile.mkdtemp(prefix="ep-h10-")
    vault = os.path.join(home, "vault")
    os.makedirs(os.path.join(vault, ".obsidian"))
    env = {"EXAM_PREP_HOME": home}
    ws = {}
    for key in ("a", "b", "c"):
        d = os.path.join(home, "exams", key)
        os.makedirs(d)
        shutil.copy(os.path.join(FIX, "answer_log_v15.csv"), os.path.join(d, "answer_log.csv"))
        ws[key] = d
    run("obsidian_sync.py", "bind", "--vault", vault, "--date", "2026-11-02", env=env)
    cfg = os.path.join(home, "obsidian_config.json")
    cfg_hash = sha(cfg)

    write(os.path.join(ws["a"], "learner_profile.json"),
          '{"exam": "a", "obsidian_write_dir": "大一上/微积分"}')
    write(os.path.join(ws["b"], "learner_profile.json"),
          '{"exam": "b", "obsidian_write_dir": ""}')
    write(os.path.join(ws["c"], "learner_profile.json"), '{"exam": "c"}')

    r = run("obsidian_sync.py", "push-errors", "--workspace", ws["a"], "--exam", "demo",
            "--date", "2026-11-02", env=env)
    local_note = os.path.join(vault, "大一上", "微积分", "errors", "demo", "遗传-分离定律.md")
    check("T10.1 局部路径生效（笔记写进用户指定文件夹）",
          r.returncode == 0 and os.path.isfile(local_note), r.stdout + r.stderr)

    r = run("obsidian_sync.py", "push-errors", "--workspace", ws["b"], "--exam", "demo",
            "--date", "2026-11-02", env=env)
    check("T10.2 答「不需要」（空值）→ 退出 3 且不写任何笔记",
          r.returncode == 3 and not os.path.isdir(os.path.join(vault, "ExamPrep")),
          r.stdout + r.stderr)

    r = run("obsidian_sync.py", "push-errors", "--workspace", ws["c"], "--exam", "demo",
            "--date", "2026-11-02", env=env)
    check("T10.3 老工作区无局部字段 → 回退全局写入区",
          r.returncode == 0 and os.path.isfile(
              os.path.join(vault, "ExamPrep", "errors", "demo", "遗传-分离定律.md")),
          r.stdout + r.stderr)

    check("T10.4 两次推送都没改全局配置", sha(cfg) == cfg_hash, "")

    r = run("obsidian_sync.py", "push-errors", "--workspace", ws["b"], "--exam", "demo",
            "--date", "2026-11-02", "--write-dir", "临时/覆盖", env=env)
    check("T10.5 --write-dir 优先于局部空值",
          r.returncode == 0 and os.path.isfile(
              os.path.join(vault, "临时", "覆盖", "errors", "demo", "遗传-分离定律.md")),
          r.stdout + r.stderr)

    write(os.path.join(ws["a"], "learner_profile.json"), '{"obsidian_write_dir": "/tmp"}')
    r = run("obsidian_sync.py", "push-errors", "--workspace", ws["a"], "--exam", "demo",
            "--dry-run", env=env)
    check("T10.6 局部绝对路径 → 退出 2", r.returncode == 2, r.stdout + r.stderr)
    write(os.path.join(ws["a"], "learner_profile.json"), '{"obsidian_write_dir": "../外"}')
    r = run("obsidian_sync.py", "push-errors", "--workspace", ws["a"], "--exam", "demo",
            "--dry-run", env=env)
    check("T10.7 局部 ../ 穿越 → 退出 2", r.returncode == 2, r.stdout + r.stderr)

    write(os.path.join(ws["a"], "learner_profile.json"),
          '{"obsidian_write_dir": "大一上/微积分"}')
    r = run("obsidian_sync.py", "check", "--workspace", ws["a"], "--exam", "demo", env=env)
    check("T10.8 check 也按局部路径核对", r.returncode == 0 and "PASS" in r.stdout,
          r.stdout + r.stderr)
    shutil.rmtree(home, ignore_errors=True)


def main():
    print("skill: %s" % SKILL)
    for fn in (t1_validate, t2_mastery_parity, t3_mastery_v15, t4_weekly,
               t5_anki_parity, t6_import_due, t7_heldout, t8_obsidian, t9_authority,
               t10_workspace_isolation):
        try:
            fn()
        except Exception as e:  # 用例崩溃也算失败，但不中断其余
            check("%s 崩溃" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))
    print("\n共 %d 项，失败 %d 项" % (CHECKS[0], len(FAILS)))
    if FAILS:
        print("失败项：%s" % "、".join(FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
