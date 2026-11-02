#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_report.py —— 周报聚合：掌握度变化 / CPKG 错因分布 / 伪装漏洞提示（plan Step 3.4）。

三要素口径：
- 掌握度变化：按模块给 总正确率、最近 5 次正确率、更早 5 次正确率与趋势差值
  （差值口径同 mastery_calc.py docstring——报告 L128；掌握度绝对值以
  mastery_calc.py 写入 syllabus_table.csv 的掌握度列为准，本脚本不重算公式整体）。
- CPKG 分布：窗口内对错=错 的行按 错因(CPKG) 计数（C/P/K/G/无/未标）。
- 伪装漏洞提示：① 同一知识点 ≥3 次 K → 疑似概念漏洞 + 强制出题 + 要求写解题步骤
  （报告 L492-498）；② 「稳」但答错 → 最高优先级 + 下次必出 + 要求解释为什么选该答案
  （报告 L500-504）。

大文件策略（报告 L763-777 分层原则）：answer_log.csv 为 append-only，默认只读
尾部窗口（--tail 条数据行，按字节块反向定位），聚合统计均为窗口口径；窗口被
截断时在输出中显式注明。窗口模式下列映射按 plan 5.2 契约核心 7 列顺序解析
（表头不在窗口内时附加列不可见，属已文档化的取舍）。
编码契约：输入必须是 UTF-8（带/不带 BOM 均可）。检测到非 UTF-8 字节（GBK/ANSI/UTF-16）
时显式 FAIL 并给「另存为 UTF-8」指引，绝不把乱码当数据静默统计（安全评审发现 3/T8）。

【Python 不可用时的降级说明】（AC-21）
PowerShell 等价（窗口内错因计数）：
  Get-Content answer_log.csv -Tail 400 | ConvertFrom-Csv |
    Group-Object '错因(CPKG)' | Select-Object Name,Count
伪装漏洞人工检查要点：在最近记录中数同一模块「K」是否 ≥3 次；凡「信心=稳且对错=错」
的行即最高优先级错题，下次复习必须重出并要求写出选择依据。
"""
import argparse
import csv
import io
import os
import sys

CORE = ["date", "模块", "题型", "对错", "信心", "错因(CPKG)", "是否留出集"]
CPKG_KEYS = ["C", "P", "K", "G", "无"]


def _reject_non_utf8(text, path):
    """解码出现替换符 U+FFFD = 输入不是合法 UTF-8（如 Excel 另存的 GBK/ANSI）。
    显式 FAIL 拒绝，避免（尤其窗口模式）把乱码当数据静默统计（安全评审发现 3/T8）。"""
    if "\ufffd" in text:
        raise SystemExit(
            "FAIL: %s 含非 UTF-8 字节（解码出现替换符）。检测到非 UTF-8 编码，"
            "请用编辑器另存为 UTF-8 后重试；Excel/WPS 用户请选「CSV UTF-8」格式保存" % path)


def read_tail(path, max_bytes):
    """读文件尾部 ≤max_bytes 字节。返回 (文本, 是否完整读入)。"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size <= max_bytes:
            text = f.read().decode("utf-8-sig", errors="replace")
            _reject_non_utf8(text, path)
            return text, True
        f.seek(size - max_bytes)
        data = f.read()
    text = data.decode("utf-8-sig", errors="replace")
    nl = text.find("\n")
    text = text[nl + 1:] if nl >= 0 else ""  # 窗口边界可能切断首行/多字节字符，先丢弃再检
    _reject_non_utf8(text, path)
    return text, False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="周报聚合：掌握度变化 / CPKG 分布 / 伪装漏洞提示（尾部窗口口径）")
    parser.add_argument("workspace", nargs="?", default=".",
                        help="考试工作区目录（默认当前目录）")
    parser.add_argument("--tail", type=int, default=400,
                        help="尾部窗口数据行数上限（默认 400）")
    parser.add_argument("--bytes", type=int, default=262144,
                        help="尾部窗口字节上限（默认 262144；两者先到为准）")
    args = parser.parse_args(argv)

    log_path = args.workspace.rstrip("/\\") + "/answer_log.csv"
    try:
        text, complete = read_tail(log_path, max(1, args.bytes))
    except OSError as e:
        sys.stderr.write("FAIL: 无法读取 %s：%s\n" % (log_path, e))
        return 1

    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    truncated = (not complete) or (len(rows) - 1 > args.tail)
    if not rows:
        sys.stderr.write("FAIL: %s 尾部窗口无内容\n" % log_path)
        return 1

    first = [c.strip() for c in rows[0]]
    if all(c in first for c in CORE):
        # 情形 A：表头在窗口内（文件小或窗口够大）
        header = first
        data = rows[1:]
    elif complete:
        # 情形 B：完整读入却无表头 → 文件本身不合契约，交 validate_log 把关
        sys.stderr.write("FAIL: %s 首行不是契约表头（缺核心列名），请先跑 validate_log.py\n" % log_path)
        return 1
    else:
        # 情形 C：尾部窗口模式，首行即数据行，按契约核心列顺序解析
        header = CORE
        data = rows
        sys.stdout.write("（尾部窗口模式：表头不在窗口内，按 plan 5.2 核心 7 列顺序解析，附加列未读取）\n")
    if truncated and len(data) > args.tail:
        data = data[-args.tail:]

    idx = {name: header.index(name) for name in CORE if name in header}
    if len(idx) < len(CORE):
        sys.stderr.write("FAIL: 列映射不完整，缺：%s\n"
                         % "、".join(n for n in CORE if n not in idx))
        return 1

    def get(row, name):
        i = idx[name]
        return row[i].strip() if len(row) > i else ""

    # v1.5 附加列：只在表头出现时聚合；缺列时输出与旧版一致（窗口模式下不可见，属文档化取舍）
    extra_idx = {n: header.index(n) for n in ("溯源", "推理链", "anki状态") if n in header}

    def getx(row, name):
        i = extra_idx.get(name)
        return row[i].strip() if (i is not None and len(row) > i) else ""

    # 聚合
    stats = {}  # 模块 -> {"n":, "ok":, "recent":[bool], "prev":[bool]}
    cpkg = {k: 0 for k in CPKG_KEYS}
    cpkg_blank = 0
    n_wrong = 0
    k_count = {}
    steady_wrong = []
    lucky = []          # 疑似蒙对：(date, 模块, 题型)
    trace_material = 0  # 溯源：材料
    trace_ai = 0        # 溯源：[AI 补充]
    trace_blank = 0
    anki_rows = []      # 待复习行：(date, 模块, 状态)
    for r in data:
        mod = get(r, "模块")
        ok_raw = get(r, "对错") == "对"
        chain = getx(r, "推理链")
        ok = ok_raw and chain != "不成立"   # 疑似蒙对按错计（仅影响趋势口径）
        conf = get(r, "信心")
        err = get(r, "错因(CPKG)")
        s = stats.setdefault(mod, {"n": 0, "ok": 0, "recent": [], "prev": []})
        s["n"] += 1
        if ok:
            s["ok"] += 1
        s["prev"].append(ok)
        if len(s["prev"]) > 10:
            s["prev"].pop(0)
        if ok_raw and chain == "不成立":
            lucky.append((get(r, "date"), mod, get(r, "题型")))
        trace = getx(r, "溯源")
        if "溯源" in extra_idx:
            if trace.startswith("[材料"):
                trace_material += 1
            elif trace.startswith("[AI 补充]"):
                trace_ai += 1
            else:
                trace_blank += 1
        anki = getx(r, "anki状态")
        if anki:
            anki_rows.append((get(r, "date"), mod, anki))
        if not ok_raw:
            n_wrong += 1
            if err in cpkg:
                cpkg[err] += 1
            else:
                cpkg_blank += 1
            if err == "K":
                k_count[mod] = k_count.get(mod, 0) + 1
            if conf == "稳":
                steady_wrong.append((get(r, "date"), mod, get(r, "题型")))

    out = []
    out.append("周报窗口：%s（%d 行数据%s）"
               % (log_path, len(data), "；窗口截断，仅统计最近记录" if truncated else ""))
    out.append("")
    out.append("== 掌握度变化（趋势口径：近5次正确率 − 更早5次正确率，报告 L128）==")
    for mod in sorted(stats):
        s = stats[mod]
        acc = s["ok"] / float(s["n"]) if s["n"] else 0.0
        recent = s["prev"][-5:]
        prev = s["prev"][:-5] if len(s["prev"]) > 5 else []
        racc = sum(recent) / float(len(recent)) if recent else 0.0
        if prev:
            pacc = sum(prev) / float(len(prev))
            delta = racc - pacc
            arrow = "↑" if delta > 1e-9 else ("↓" if delta < -1e-9 else "→")
            trend_s = "近5次 %.0f%% vs 更早 %.0f%%  %s %+.2f" % (racc * 100, pacc * 100, arrow, delta)
        else:
            trend_s = "近5次 %.0f%%（更早记录不足，趋势无信号）" % (racc * 100)
        out.append("  %s：作答 %d 次，总正确率 %.0f%%；%s"
                   % (mod, s["n"], acc * 100, trend_s))
    out.append("  （掌握度绝对值以 mastery_calc.py 写入 syllabus_table.csv 的掌握度列为准）")
    if "推理链" in extra_idx:
        out.append("  （v1.5 趋势口径：疑似蒙对按错计；CPKG 与伪装漏洞仍按记录的对错统计）")
    out.append("")
    out.append("== CPKG 错因分布（窗口内错误行 %d 条）==" % n_wrong)
    for k in CPKG_KEYS:
        pct = (cpkg[k] / float(n_wrong) * 100) if n_wrong else 0.0
        out.append("  %s：%d 条（%.0f%%）" % (k, cpkg[k], pct))
    out.append("  未标错因：%d 条（建议补标，D-7 用户自标为主）" % cpkg_blank)
    out.append("")
    out.append("== 伪装漏洞提示 ==")
    hit = False
    for mod in sorted(k_count):
        if k_count[mod] >= 3:
            hit = True
            out.append("  [疑似概念漏洞] %s：K 类错误 %d 次（≥3）→ 强制出题 + 要求写解题步骤"
                       % (mod, k_count[mod]))
    if steady_wrong:
        hit = True
        out.append("  [最高优先级] 「稳」但答错 %d 条（下次必出，要求解释为什么选该答案）：" % len(steady_wrong))
        for d, mod, typ in steady_wrong:
            out.append("    - %s %s（%s）" % (d, mod, typ))
    if not hit:
        out.append("  （窗口内未触发：无 ≥3 次 K 的模块，无「稳而错」记录）")
    out.append("")

    # v1.5 三段：仅在对应附加列存在时输出（缺列 → 与旧版逐字节一致）
    if "推理链" in extra_idx:
        out.append("== 疑似蒙对（答案对但推理链不成立 / 未写，不计入掌握度分子）==")
        if lucky:
            out.append("  [不计入掌握度] 疑似蒙对 %d 条（强制进变式题池，变式题要求写出推理链）：" % len(lucky))
            for d, mod, typ in lucky:
                out.append("    - %s %s（%s）" % (d, mod, typ))
        n_unwritten = sum(1 for r in data if get(r, "对错") == "对" and getx(r, "推理链") == "未写")
        if n_unwritten:
            out.append("  [提示] 推理链=未写 %d 条（外部录入题可豁免，技能出题请补）" % n_unwritten)
        if not lucky and not n_unwritten:
            out.append("  （窗口内无疑似蒙对：每道答对的题都有成立的推理链）")
        out.append("")
    if "溯源" in extra_idx:
        out.append("== 溯源分布（防幻觉观测，不参与掌握度）==")
        total_trace = trace_material + trace_ai + trace_blank
        out.append("  [材料 …] %d 条；[AI 补充] %d 条；未标 %d 条（共 %d 条）"
                   % (trace_material, trace_ai, trace_blank, total_trace))
        if trace_ai:
            out.append("  [提示] [AI 补充] 条目在材料里没有对应出处，复习时以材料原文为准")
        out.append("")
    if "anki状态" in extra_idx:
        out.append("== Anki 调度回填（超期未过 / 重新学习）==")
        if anki_rows:
            out.append("  待复习 %d 条：掌握度按 (1 − w × frac_due) 折扣，w 默认 0.15" % len(anki_rows))
            for d, mod, st in anki_rows:
                out.append("    - %s %s（%s）" % (d, mod, st))
        else:
            out.append("  （未回填：如需把 Anki 到期未过/重新学习纳入掌握度，用 export_anki.py --import-due）")
        out.append("")

    sys.stdout.write("\n".join(out))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
