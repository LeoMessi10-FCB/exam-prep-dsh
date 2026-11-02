#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""verify_heldout.py —— 留出集 SHA-256 哈希记录与校验（plan 5.5 / D-4 / AC-11）。

用法（双模式，二选一）：
  python verify_heldout.py --record  <held_out.md>   # 建库时：生成同目录 <文件名>.sha256
  python verify_heldout.py --verify  <held_out.md>   # 重测前：校验，FAIL=非零退出+stderr 诊断

哈希文件契约（逐字，sha256sum 兼容）：与 held_out.md 同目录、名为 held_out.md.sha256，
内容一行 `<小写hex>␣␣held_out.md`（哈希与文件名之间两空格）。因此在校验目录内
`sha256sum -c held_out.md.sha256`（Linux/Git-Bash）与 --verify 等价。

判定：--verify 时哈希缺失/文件名不符/哈希不一致 → stderr 诊断 + 退出码 1；
一致 → stdout PASS + 退出码 0。校验 FAIL 后的处置（D-4）：询问用户是否有意修改——
有意 → 重新 --record 并注明日期；无意 → 从备份恢复（建议 git 或 held_out.md.bak）。

【Python 不可用时的降级说明】（AC-21；plan 5.5 指定）
PowerShell 等价命令：
  # 记录（生成 held_out.md.sha256，注意两空格格式）：
  "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 .\held_out.md).Hash.ToLower(), 'held_out.md' |
    Set-Content -NoNewline:$false -Encoding ascii .\held_out.md.sha256
  # 校验（重测前必跑）：
  $want = (Get-Content .\held_out.md.sha256 -TotalCount 1).Split(' ')[0]
  $got  = (Get-FileHash -Algorithm SHA256 .\held_out.md).Hash.ToLower()
  if ($want -ne $got) { Write-Error 'held_out 哈希不一致！' } else { 'PASS' }
手动检查要点：哈希行 64 位小写十六进制 + 两空格 + 文件名；不一致=留出集已被改动，
测量层结果作废，先按 D-4 处置再重测。
"""
import argparse
import hashlib
import os
import sys


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="留出集哈希记录/校验（SHA-256，sha256sum 兼容两空格格式）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", metavar="HELD_OUT",
                      help="建库时：为该文件生成 <文件名>.sha256")
    mode.add_argument("--verify", metavar="HELD_OUT",
                      help="重测前：校验该文件与其 .sha256 是否一致")
    args = parser.parse_args(argv)

    target = args.record if args.record is not None else args.verify
    if not os.path.isfile(target):
        sys.stderr.write("FAIL: 文件不存在：%s\n" % target)
        return 1
    digest = sha256_of(target)
    base = os.path.basename(target)
    hash_path = target + ".sha256"

    if args.record is not None:
        with open(hash_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("%s  %s\n" % (digest, base))
        sys.stdout.write("已记录：%s\n%s  %s\n" % (hash_path, digest, base))
        return 0

    # --verify
    if not os.path.isfile(hash_path):
        sys.stderr.write("FAIL: 哈希文件不存在：%s（建库时须先 --record 一次）\n" % hash_path)
        return 1
    with open(hash_path, "r", encoding="utf-8-sig") as f:
        line = f.readline().strip()
    parts = line.split()
    if len(parts) < 2 or len(parts[0]) != 64 or any(c not in "0123456789abcdef" for c in parts[0].lower()):
        sys.stderr.write("FAIL: 哈希文件格式非法（应为 `<64位小写hex>␣␣<文件名>`）：%s\n" % hash_path)
        return 1
    want_hash, want_name = parts[0].lower(), " ".join(parts[1:])
    if want_name != base:
        sys.stderr.write("FAIL: 哈希行指向的文件名不符（行内=%s，实际=%s）：%s\n"
                         % (want_name, base, hash_path))
        return 1
    if want_hash != digest:
        sys.stderr.write("FAIL: 留出集哈希不一致！\n")
        sys.stderr.write("  记录值：%s\n" % want_hash)
        sys.stderr.write("  当前值：%s\n" % digest)
        sys.stderr.write("  文件：%s 自上次记录后被改动。按 D-4 处置：有意修改→重新 --record 并注明日期；"
                         "无意→从备份恢复（git / held_out.md.bak）。测量层结果在恢复前不可用。\n" % target)
        return 1
    sys.stdout.write("PASS：%s 与 %s 一致（sha256=%s）\n" % (target, hash_path, digest))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
