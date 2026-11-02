#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""validate_log.py —— answer_log.csv 契约校验（plan 5.2 / AC-13 / AC-22）。

契约要点（真源：docs/plans/autopilot-exam-prep.md 5.2 节）：
- 表头核心列（逐字，允许附加列，缺任一核心列 FAIL）：
  date,模块,题型,对错,信心,错因(CPKG),是否留出集
- 枚举：对错 ∈ {对,错}；题型 ∈ {客观,主观}；信心 ∈ {稳,不确定,蒙}（可空，空=WARN）；
  错因(CPKG) ∈ {C,P,K,G,无}（可空，空=WARN）；是否留出集 ∈ {是,否}
- date 格式 YYYY-MM-DD；append-only（本脚本只读，不改历史行）。
- v1.5 附加列（**列不存在则完全不校验，行为与旧版逐字节一致**）：
  推理链 ∈ {成立,不成立,未写}（空=WARN）；anki状态 ∈ {未过,重学}（空=WARN）；
  溯源 形态须为 `[材料 <文件名> p.N]`、`[材料 <文件名> §<标题>]` 或 `[AI 补充]` 之一
  （形态不符=WARN：溯源是自由文本，脚本只查括注形态，不查页码是否真实存在）。
判定：FAIL → stderr 诊断（含行号）+ 退出码 1；WARN 只提示不影响退出码；合法 → PASS 退出码 0。
注：空行跳过并 WARN；读取用 utf-8-sig（容忍 Windows 工具写入的 BOM），写出不涉及；
非 UTF-8 输入（GBK/ANSI/UTF-16 等）显式 FAIL 并附「另存为 UTF-8」恢复指引，不抛裸 traceback。

【Python 不可用时的降级说明】（AC-21）
PowerShell 手动检查要点：
  # 1) 表头核对（核心 7 列逐字在场）：
  (Import-Csv answer_log.csv).PSObject.Properties.Name -join ','
  # 2) 枚举越界行（以对错列为例，越界则输出行对象）：
  Import-Csv answer_log.csv | Where-Object { $_.'对错' -notin @('对','错') }
  # 3) 空信心/错因行（应 WARN 不阻断）：
  Import-Csv answer_log.csv | Where-Object { [string]::IsNullOrWhiteSpace($_.'信心') }
  # 4) date 形如 2026-01-05（正则粗检）：
  Import-Csv answer_log.csv | Where-Object { $_.date -notmatch '^\d{4}-\d{2}-\d{2}$' }
  # 5) v1.5 列（仅当表头有该列时）：
  Import-Csv answer_log.csv | Where-Object { $_.'推理链' -notin @('成立','不成立','未写','') }
  Import-Csv answer_log.csv | Where-Object { $_.'溯源' -notmatch '^\[(材料 .+|AI 补充)\]$' }
手动检查要点：核心列缺一即不合格；枚举越界行必须改正；信心/错因留空只提示补标不阻断。
"""
import argparse
import csv
import datetime
import re
import sys

CORE_COLUMNS = ["date", "模块", "题型", "对错", "信心", "错因(CPKG)", "是否留出集"]
ENUMS = {
    "对错": ("对", "错"),
    "题型": ("客观", "主观"),
    "是否留出集": ("是", "否"),
}
ENUMS_OPTIONAL = {
    "信心": ("稳", "不确定", "蒙"),
    "错因(CPKG)": ("C", "P", "K", "G", "无"),
}
# v1.5 新增附加列：仅在表头出现该列时校验
ENUMS_V15 = {
    "推理链": ("成立", "不成立", "未写"),
    "anki状态": ("未过", "重学"),
}
# 空值是否 WARN：推理链是技能出题的义务（空=没写），anki状态 是可选信号（空=尚未回填，不告警）
V15_EMPTY_WARN = {"推理链"}
# 溯源形态：材料页码 / 材料小节 / AI 推断声明
TRACE_RES = (
    re.compile(r"^\[材料 .+ p\.\d+\]$"),
    re.compile(r"^\[材料 .+ §[^\]]+\]$"),
    re.compile(r"^\[AI 补充\]$"),
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fail(msg):
    sys.stderr.write("FAIL: %s\n" % msg)


def warn(msg):
    sys.stderr.write("WARN: %s\n" % msg)


def validate(path):
    """校验一个 answer_log.csv。返回 0=PASS（可含 WARN），1=FAIL。"""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    except UnicodeDecodeError as e:
        fail("文件 %s 不是 UTF-8 编码（无效字节 0x%02x 于偏移 %d）。"
             "检测到非 UTF-8 编码，请用编辑器另存为 UTF-8 后重试；"
             "Excel/WPS 用户请选「CSV UTF-8」格式保存"
             % (path, e.object[e.start] if e.object else 0, e.start))
        return 1
    except OSError as e:
        fail("无法读取文件 %s：%s" % (path, e))
        return 1

    if not rows:
        fail("文件为空：缺少表头行")
        return 1

    header = [h.strip() for h in rows[0]]
    header_line = 1

    # 1) 核心列齐备性（AC-13：缺任一核心列 FAIL）
    missing = [c for c in CORE_COLUMNS if c not in header]
    if missing:
        fail("第 %d 行表头缺核心列：%s（核心列须为 %s；允许附加列）"
             % (header_line, "、".join(missing), ",".join(CORE_COLUMNS)))
        return 1
    if len(set(header)) != len(header):
        dup = sorted({h for h in header if header.count(h) > 1})
        fail("第 %d 行表头存在重复列名：%s" % (header_line, "、".join(dup)))
        return 1

    col_index = {name: header.index(name) for name in header}
    n_fail = 0
    n_warn = 0
    n_data = 0

    # 逐行校验（常规日志一行=一物理行；行内不含裸换行）
    physical_line = 1
    for row in rows[1:]:
        physical_line += 1
        if not row or all(not c.strip() for c in row):
            warn("第 %d 行为空行，已跳过" % physical_line)
            n_warn += 1
            continue
        n_data += 1
        # 2) 列数对齐
        if len(row) != len(header):
            fail("第 %d 行列数 %d ≠ 表头列数 %d（列错位/列数不足）"
                 % (physical_line, len(row), len(header)))
            n_fail += 1
            continue
        get = lambda name: row[col_index[name]].strip()
        # 3) 必填文本列
        for name in ("date", "模块", "对错", "题型", "是否留出集"):
            if not get(name):
                fail("第 %d 行必填列「%s」为空" % (physical_line, name))
                n_fail += 1
        # 4) date 格式 YYYY-MM-DD（正则 + 真实日历校验）
        d = get("date")
        if d:
            if not DATE_RE.match(d):
                fail("第 %d 行 date「%s」不符合 YYYY-MM-DD" % (physical_line, d))
                n_fail += 1
            else:
                try:
                    datetime.datetime.strptime(d, "%Y-%m-%d")
                except ValueError:
                    fail("第 %d 行 date「%s」不是真实日期（如 2026-02-30）" % (physical_line, d))
                    n_fail += 1
        # 5) 必填枚举
        for name, allowed in ENUMS.items():
            v = get(name)
            if v and v not in allowed:
                fail("第 %d 行「%s」值「%s」越界，合法值：%s"
                     % (physical_line, name, v, "/".join(allowed)))
                n_fail += 1
        # 6) 可空枚举：空=WARN，非空越界=FAIL（AC-22）
        for name, allowed in ENUMS_OPTIONAL.items():
            v = get(name)
            if not v:
                warn("第 %d 行可选列「%s」为空（建议补标，不阻断）" % (physical_line, name))
                n_warn += 1
            elif v not in allowed:
                fail("第 %d 行「%s」值「%s」越界，合法值：%s"
                     % (physical_line, name, v, "/".join(allowed)))
                n_fail += 1
        # 7) v1.5 附加列：仅当表头含该列时校验（列不存在 → 零影响，保证旧日志行为不变）
        for name, allowed in ENUMS_V15.items():
            if name not in col_index:
                continue
            v = get(name)
            if not v:
                if name in V15_EMPTY_WARN:
                    warn("第 %d 行 v1.5 列「%s」为空（建议补标，不阻断）" % (physical_line, name))
                    n_warn += 1
            elif v not in allowed:
                fail("第 %d 行「%s」值「%s」越界，合法值：%s"
                     % (physical_line, name, v, "/".join(allowed)))
                n_fail += 1
        # 8) 溯源形态（只查形态，不查页码真实性）：不符=WARN
        if "溯源" in col_index:
            v = get("溯源")
            if not v:
                warn("第 %d 行「溯源」为空（建议补标 [材料 …] 或 [AI 补充]，不阻断）" % physical_line)
                n_warn += 1
            elif not any(r.match(v) for r in TRACE_RES):
                warn("第 %d 行「溯源」值「%s」形态不符（应为 [材料 文件名 p.N] / "
                     "[材料 文件名 §标题] / [AI 补充]）" % (physical_line, v))
                n_warn += 1

    sys.stdout.write("校验对象：%s\n数据行：%d；FAIL：%d；WARN：%d\n"
                     % (path, n_data, n_fail, n_warn))
    if n_fail:
        sys.stdout.write("结论：FAIL\n")
        return 1
    sys.stdout.write("结论：PASS%s\n" % ("（含 WARN）" if n_warn else ""))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="answer_log.csv 契约校验（plan 5.2；FAIL 指出行号，空信心/错因仅 WARN）")
    parser.add_argument("log", nargs="?", default="answer_log.csv",
                        help="answer_log.csv 路径（默认 ./answer_log.csv）")
    args = parser.parse_args(argv)
    return validate(args.log)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
