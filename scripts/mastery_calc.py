#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mastery_calc.py —— 掌握度计算并写入 syllabus_table.csv 建议值（D-12 / AC-23）。

公式（逐字采自 docs/specs/交互式考试备考Skill实施报告.md L123-124）：
    掌握度 = f(正确率, 信心度, 近期趋势, 作答次数)
           = 0.4 × 正确率 + 0.3 × (1 - 高置信度错误惩罚) + 0.2 × 近期正确率趋势 + 0.1 × 作答充分度

含糊术语解读（本脚本的实现口径，均注明依据行号，未自行发明）：
- 正确率 = 该知识点下所有作答的正确比例（报告 L126 逐字）。
- 「高置信度错误惩罚」：报告未给显式公式。本实现取
    penalty = (信心=稳 且 对错=错 的作答数) / (该知识点总作答数)
  依据：① 报告 L500 逐字定义「高置信度错误（"稳"但答错）」——报告自身就把
  「稳而错」称为高置信度错误；② 报告 L500-504 给其处置为最高优先级，
  说明该量的语义就是「稳而错的占比/存在性」对掌握度的扣减；
  ③ 报告 L127 信心度映射「稳=1.0、不确定=0.5、蒙=0.2，乘以正确率」确立
  「稳」为最高置信档（本实现仅用该映射做「高置信度=稳」的判定依据，
  不把它单独乘进正确率项——公式第二项的(1-惩罚)结构与 L127 的加权式
  并不自洽，二者取公式本体优先）。
  备选解读（方向等价，不影响 AC-23 断言）：penalty = 错误行置信权重均值
  （Σ conf(错行)/n）。两种解读下「A 全对(B 全错)」均有 mastery(A) > mastery(B)。
- 近期趋势 = 最近 5 次作答正确率 − 更早 5 次作答正确率（报告 L128 逐字）。
  实现口径：按 answer_log 文件顺序（append-only ⇒ 时间序）；「更早 5 次」
  取倒数第 6~10 条（不足 5 条用全部更早记录；没有更早记录时趋势=0.0，
  属实现补全——L128 未定义样本不足情形）。趋势 ∈ [-1, 1]。
- 作答充分度 = min(作答次数, 5) / 5（报告 L129「建议至少 5 次」的归一化实现）。
- 最终值截断到 [0, 1]（趋势可为负使裸和下探 -0.2），输出两位小数（plan 5.3 契约）。

v1.5 两项可选修正（都由 answer_log 的附加列触发；**列不存在时输出与旧版逐字节一致**）：
1. 推理链优先（附加列「推理链」）：`对错=对 且 推理链=不成立` 的行是「疑似蒙对」，
   在正确率、高置信度错误惩罚、趋势三处一律按错计——它证明的是运气不是掌握。
   `推理链=未写` 不惩罚（外部录入题常无过程），只在周报里计数。
   `--ignore-chain` 可临时关闭该修正（仅用于回归对照，不是日常开关）。
2. Anki 调度折扣（附加列「anki状态」）：
     frac_due = 该模块 anki状态 非空的行数 / 该模块总行数
     mastery  = clamp(base × (1 - w × frac_due), 0, 1)      w 默认 0.15（--anki-weight）
   乘性而非加第五项的理由：四项语义不被破坏、折扣单独可解释为「调度违和」、恒 ≤ base；
   推导与算例见 references/anki_scheduling.md。折扣只影响建议值，不覆盖你手改的值（D-12）。

D-12 行为（用户手改行提示差异不覆盖）：
- 掌握度列为空 → 写入建议值；
- 列已有值且与建议一致 → 不动；
- 列已有值且与建议不同 → 视为用户手改，保留用户值，仅打印差异提示
  （无来源标记可区分「旧建议」与「手改」，一律按手改处理——宁可不覆盖）。
- stdout 恒为「建议值清单」（确定性输出，两次运行完全一致，服务 AC-23）；
  文件动作与差异提示走 stderr。
- 写回编码：若 syllabus_table.csv 原带 UTF-8 BOM（Excel「CSV UTF-8」保存），写回保留 BOM，
  避免无 BOM 文件被 Excel 按 ANSI 误读（安全评审发现 7）；无 BOM 输入写回仍无 BOM。
- 非 UTF-8 输入（GBK/ANSI/UTF-16 等）：显式 FAIL + 「另存为 UTF-8」指引，不抛裸 traceback。

【Python 不可用时的降级说明】（AC-21）
无 Python 时可按上表公式人工/Excel 口算：正确率=对行数/总行数；
惩罚=稳而错行数/总行数；趋势=近5次对比例−更早5次对比例；充分度=MIN(次数,5)/5。
PowerShell 快速核对正确率：
  $r = Import-Csv exams/<考试标识>/answer_log.csv
  ($r | Where-Object { $_.'模块' -eq '某模块' -and $_.'对错' -eq '对' }).Count /
  ($r | Where-Object { $_.'模块' -eq '某模块' }).Count
掌握度列手填两位小数（0-1）即可；手改后脚本重算只提示差异不覆盖。
"""
import argparse
import csv
import sys

CONF_WEIGHTS = {"稳": 1.0, "不确定": 0.5, "蒙": 0.2}  # 报告 L127 映射（判定依据用）
RECENT_N = 5
FULL_N = 5


def fail(msg):
    sys.stderr.write("FAIL: %s\n" % msg)


def encoding_fail_msg(path, e):
    return ("文件 %s 不是 UTF-8 编码（无效字节 0x%02x 于偏移 %d）。"
            "检测到非 UTF-8 编码，请用编辑器另存为 UTF-8 后重试；"
            "Excel/WPS 用户请选「CSV UTF-8」格式保存"
            % (path, e.object[e.start] if e.object else 0, e.start))


def read_csv_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    data = [r for r in rows[1:] if any(c.strip() for c in r)]
    return header, data


def module_rows(header, data, strict_chain=True):
    """按模块分组 answer_log 数据行（保持文件顺序=时间序）。

    v1.5：表头含「推理链」且 strict_chain 时，`对错=对 且 推理链=不成立` 的行按错计
    （疑似蒙对）；表头含「anki状态」时记录该行是否待复习（未过/重学）。
    返回 rows: [(对生效: bool, 信心: str, anki待复习: bool)]
    """
    try:
        i_mod = header.index("模块")
        i_right = header.index("对错")
        i_conf = header.index("信心")
    except ValueError as e:
        raise SystemExit("FAIL: answer_log 缺核心列：%s（先跑 validate_log.py）" % e)
    i_chain = header.index("推理链") if ("推理链" in header and strict_chain) else None
    i_anki = header.index("anki状态") if "anki状态" in header else None

    def cell(row, i):
        return row[i].strip() if (i is not None and len(row) > i) else ""

    groups = {}
    for r in data:
        if len(r) <= max(i_mod, i_right, i_conf):
            continue
        mod = r[i_mod].strip()
        if not mod:
            continue
        ok = r[i_right].strip() == "对"
        if i_chain is not None and cell(r, i_chain) == "不成立":
            ok = False  # 疑似蒙对：不计入掌握度分子
        groups.setdefault(mod, []).append(
            (ok, r[i_conf].strip(), bool(cell(r, i_anki))))
    return groups


def mastery(rows, anki_weight=0.15):
    """rows: [(对生效, 信心, anki待复习)] 按时间序。

    返回 (掌握度建议值, base, frac_due)：
    - base 为蓝本四项公式结果（0.4/0.3/0.2/0.1）；
    - frac_due = anki待复习行数 / 总行数；为 0 时**不进入乘法**，保证旧日志逐字节等价；
    - 最终值 clamp 到 [0,1]。
    """
    n = len(rows)
    acc = sum(1 for ok, _, _ in rows if ok) / float(n)
    penalty = sum(1 for ok, c, _ in rows if (not ok) and c == "稳") / float(n)
    last = rows[-RECENT_N:]
    prev = rows[-2 * RECENT_N:-RECENT_N]
    if prev:
        trend = (sum(1 for ok, _, _ in last if ok) / float(len(last))
                 - sum(1 for ok, _, _ in prev if ok) / float(len(prev)))
    else:
        trend = 0.0
    suff = min(n, FULL_N) / float(FULL_N)
    base = 0.4 * acc + 0.3 * (1.0 - penalty) + 0.2 * trend + 0.1 * suff
    frac_due = sum(1 for _, _, due in rows if due) / float(n)
    val = base
    if frac_due > 0.0:
        val = base * (1.0 - anki_weight * frac_due)
    return max(0.0, min(1.0, val)), base, frac_due


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="掌握度计算（报告 L123-129 公式）→ 写 syllabus_table.csv 建议值（D-12：手改行提示差异不覆盖）")
    parser.add_argument("workspace", nargs="?", default=".",
                        help="考试工作区目录（默认当前目录；读其中 answer_log.csv 与 syllabus_table.csv）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印建议值，不写 syllabus_table.csv")
    parser.add_argument("--anki-weight", type=float, default=0.15, metavar="W",
                        help="Anki 调度折扣权重（默认 0.15；frac_due=0 时不进入计算）")
    parser.add_argument("--ignore-chain", action="store_true",
                        help="忽略「推理链=不成立」修正（仅用于与旧版对照，非日常开关）")
    args = parser.parse_args(argv)

    log_path = args.workspace.rstrip("/\\") + "/answer_log.csv"
    syl_path = args.workspace.rstrip("/\\") + "/syllabus_table.csv"
    try:
        with open(syl_path, "rb") as f:
            syl_had_bom = f.read(3) == b"\xef\xbb\xbf"
    except OSError:
        syl_had_bom = False  # 文件不存在时由下方读取路径给出 FAIL
    try:
        header, data = read_csv_rows(log_path)
    except UnicodeDecodeError as e:
        fail(encoding_fail_msg(log_path, e))
        return 1
    except OSError as e:
        fail("无法读取 %s：%s" % (log_path, e))
        return 1
    try:
        syl_header, syl_rows = read_csv_rows(syl_path)
    except UnicodeDecodeError as e:
        fail(encoding_fail_msg(syl_path, e))
        return 1
    except OSError as e:
        fail("无法读取 %s：%s" % (syl_path, e))
        return 1
    # 尾列为空的行（如 "C,中,"）解析后比表头短 → 按表头长度原地补齐空字段（保持行序），避免误跳过
    syl_rows = [r + [""] * (len(syl_header) - len(r)) if len(r) < len(syl_header) else r
                for r in syl_rows]

    groups = module_rows(header, data, strict_chain=not args.ignore_chain)
    if not groups:
        fail("%s 无有效作答数据（模块列全空或无数据行）" % log_path)
        return 1

    try:
        i_mod = syl_header.index("模块")
        i_mas = syl_header.index("我的掌握度")
    except ValueError as e:
        fail("%s 缺列：%s（契约：模块,权重档,最近出现年份,我的掌握度）" % (syl_path, e))
        return 1

    # 计算全部建议值（stdout 确定性输出）
    suggestions = {}          # 模块 -> "0.87"
    ordered_mods = []         # 考点表行序
    seen = set()
    for r in syl_rows:
        if len(r) <= max(i_mod, i_mas):
            continue
        mod = r[i_mod].strip()
        if mod and mod not in seen:
            seen.add(mod)
            ordered_mods.append(mod)
    def suggest(mod):
        """返回两位小数字符串；Anki 折扣的诊断走 stderr（stdout 保持确定性）。"""
        val, base, frac_due = mastery(groups[mod], anki_weight=args.anki_weight)
        if frac_due > 0.0:
            sys.stderr.write(
                "Anki 调度折扣：%s frac_due=%.2f base=%.2f → %.2f（w=%.2f）\n"
                % (mod, frac_due, base, val, args.anki_weight))
        return "%.2f" % val

    for mod in ordered_mods:
        if mod in groups:
            suggestions[mod] = suggest(mod)
    unmatched = sorted(m for m in groups if m not in seen)
    for mod in unmatched:
        suggestions[mod] = suggest(mod)

    for mod in ordered_mods + unmatched:
        if mod in suggestions:
            tag = "" if mod in seen else "（未在考点表，建议建库时补行）"
            sys.stdout.write("掌握度建议  %s  %s%s\n" % (mod, suggestions[mod], tag))

    if args.dry_run:
        sys.stdout.write("（--dry-run：未写入 %s）\n" % syl_path)
        return 0

    # 写入：仅填空单元格；非空不一致 → 保留 + 差异提示（D-12）
    changed = False
    for r in syl_rows:
        if len(r) <= max(i_mod, i_mas):
            continue
        mod = r[i_mod].strip()
        if mod not in suggestions:
            continue
        cur = r[i_mas].strip()
        sug = suggestions[mod]
        if not cur:
            r[i_mas] = sug
            changed = True
            sys.stderr.write("已写入建议值：%s = %s（原为空）\n" % (mod, sug))
        elif cur != sug:
            sys.stderr.write("差异提示（保留手改值，未覆盖 D-12）：%s 当前=%s 建议=%s；"
                             "如需采纳建议请手动清空该单元格后重跑\n" % (mod, cur, sug))
    if changed:
        with open(syl_path, "w", encoding="utf-8-sig" if syl_had_bom else "utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(syl_header)
            w.writerows(syl_rows)
        sys.stderr.write("已更新 %s\n" % syl_path)
    else:
        sys.stderr.write("%s 无需改动\n" % syl_path)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
