#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_pdf.py —— 文本层 PDF → Markdown 提取（GATE-1 修订附录 §3/§4：N-7 细化 / AC-26 前置）。

引擎（--engine 选择；缺省 auto）：
  auto = 1) pymupdf4llm（若已装）→ 2) pymupdf 裸文本 + 轻量 md 结构包装
     （大题题头正则「一、二、…」→ 二级标题；字号高于正文基准 ≥1.5pt 且 <60 字
     → 三级标题；_dev/probe_md.py 原型已验证，验收运行采此级）
  两库皆缺 → 打印「请用 pdftotext / 在线转换 / 手工复制」指引后退出，
     不 crash（退出码 3，不写任何文件）
  --engine markitdown = 走微软 markitdown（需用户终端自行安装）。引擎实测对比
     （2025 期末卷同 PDF 同口径）：题号行 pymupdf 40 vs markitdown 9（题号被
     切碎进布局表格）、表格碎屑行 4 vs 460、解析覆盖 24 vs 24——auto 不自动
     选 markitdown；它适合 Office 文档（docx/xlsx/pptx 可直接用 markitdown CLI）
     或用户显式偏好。

用法：
  python extract_pdf.py <单个.pdf 或 目录> [--outdir DIR] [--recursive] [--force] [--engine {auto,pymupdf,markitdown}]
- 目录批量：收集 *.pdf（含 .PDF，大小写不敏感；--recursive 递归子目录），
  按路径排序逐个提取；每个 PDF 输出 <outdir>/<stem>.md。
- 提取状态清单：<outdir>/extract_status.csv（UTF-8 无 BOM），列：
  源文件,输出文件,状态,页数,字符数,二级题头数,备注
  状态 ∈ OK / OK_OVERWRITE / SKIP_SAME（目标已存在且内容相同）/ SKIP_EXISTS
  （目标已存在且不同，未加 --force，保留旧文件）/ NO_TEXT_LAYER（无可提取文本层，
  疑似扫描件，不写 .md）/ FAIL（解析异常，备注含原因）。
- 退出码：0=全部 OK/SKIP；1=存在 FAIL 或 NO_TEXT_LAYER；2=参数/输入错误；3=库缺失。
- 注意：不做 OCR/扫描件（spec N-7 细化后边界不变）；公式线性化损耗已知
  （修订附录 §4.5：建库以考点/结构/分值为主，不追求公式保真）。

【Python 不可用时的降级说明】（AC-21）
  # 有 pdftotext（poppler）时逐文件转文本再人工补结构：
  pdftotext -enc UTF-8 输入.pdf 输出.txt
  # 或用 PowerShell + 已装库的等价哈希校验思路不可行（本脚本依赖 PDF 解析库），
  # 降级主路径 = 在线转换工具或手工复制粘贴；提取后仍需满足 AC-26 抽检：
  # 题号、大题题头含分值的结构行（如「一、选择题（共7 题，每题3 分，共21 分）」）在场。
"""
import argparse
import csv
import os
import re
import sys

SEC_RE = re.compile(u"^[一二三四五六七八九十]+、")
MIN_CHARS = 20  # 低于此字符数判 NO_TEXT_LAYER（标题行除外）


def have_pymupdf4llm():
    try:
        import pymupdf4llm  # noqa: F401
        return True
    except Exception:
        return False


def have_pymupdf():
    try:
        import pymupdf  # noqa: F401
        return True
    except Exception:
        return False


def to_md_via_4llm(pdf_path):
    import pymupdf4llm
    return pymupdf4llm.to_markdown(pdf_path)


def have_markitdown():
    try:
        import markitdown  # noqa: F401
        return True
    except Exception:
        return False


def to_md_via_markitdown(pdf_path):
    from markitdown import MarkItDown
    r = MarkItDown().convert(str(pdf_path))
    return r.text_content or ""


def to_md_via_pymupdf(pdf_path):
    """轻量 md 包装（_dev/probe_md.py 已验证逻辑的函数化，验收主用级）。"""
    import pymupdf
    from collections import Counter
    doc = pymupdf.open(pdf_path)
    try:
        out = ["# %s\n" % os.path.splitext(os.path.basename(pdf_path))[0]]
        all_lines = []
        for page in doc:
            d = page.get_text("dict")
            for block in d["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if text:
                        sizes = [s["size"] for s in line["spans"]]
                        all_lines.append((text, max(sizes)))
        if not all_lines:
            return "\n".join(out), len(doc)
        # 正文基准字号 = 出现次数最多的字号（近似众数，取整）——probe 同款启发式
        body_size = Counter(round(s) for _, s in all_lines).most_common(1)[0][0]
        for text, size in all_lines:
            if SEC_RE.match(text):
                out.append("\n## %s\n" % text)
            elif size >= body_size + 1.5 and len(text) < 60:
                out.append("\n### %s\n" % text)
            else:
                out.append(text)
        return "\n".join(out), len(doc)
    finally:
        doc.close()


def h2_count(md_text):
    return sum(1 for l in md_text.splitlines() if l.startswith("## "))


def collect_pdfs(inp, recursive):
    if os.path.isfile(inp):
        return [inp]
    found = []
    if recursive:
        for root, _dirs, files in os.walk(inp):
            for fn in files:
                if fn.lower().endswith(".pdf"):
                    found.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(inp):
            if fn.lower().endswith(".pdf") and os.path.isfile(os.path.join(inp, fn)):
                found.append(os.path.join(inp, fn))
    return sorted(found, key=lambda p: p.lower())


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="文本层 PDF → Markdown（三级兜底：pymupdf4llm → pymupdf 轻量包装 → 降级指引）")
    parser.add_argument("input", help="单个 PDF 文件或目录")
    parser.add_argument("--outdir", default=None,
                        help="输出目录（默认：单文件=其所在目录；目录输入=该目录）")
    parser.add_argument("--recursive", action="store_true", help="目录输入时递归子目录")
    parser.add_argument("--force", action="store_true",
                        help="目标 .md 已存在且内容不同时覆盖（缺省保留旧文件并记 SKIP_EXISTS）")
    parser.add_argument("--engine", choices=["auto", "pymupdf", "markitdown"], default="auto",
                        help="提取引擎（缺省 auto：pymupdf4llm→pymupdf 轻量包装；markitdown 适合 Office 文档或显式偏好）")
    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        sys.stderr.write("FAIL: 输入不存在：%s\n" % args.input)
        return 2
    if args.engine == "markitdown":
        if not have_markitdown():
            sys.stderr.write("FAIL: --engine markitdown 但 markitdown 不可用。"
                             "请先在终端 pip install --user \"markitdown[pdf]\"，"
                             "或改用缺省 auto 引擎（pymupdf 轻量包装）。\n")
            return 3
        level = 3
    else:
        level = 1 if (args.engine == "auto" and have_pymupdf4llm()) else (
            2 if have_pymupdf() else 0)
    if level == 0:
        msg = ("本机缺 PDF 解析库（pymupdf4llm / pymupdf 均不可用），未做任何转换。\n"
               "降级路径（按序尝试）：① pdftotext -enc UTF-8 输入.pdf 输出.txt（poppler）；"
               "② 在线 PDF→Markdown 转换工具；③ 手工复制文本层内容。\n"
               "安装任一库后重跑本脚本即可自动化。")
        sys.stdout.write(msg)
        sys.stderr.write("FAIL: 库缺失，extract_pdf 以降级指引退出（exit 3）\n")
        return 3

    pdfs = collect_pdfs(args.input, args.recursive)
    if not pdfs:
        sys.stderr.write("FAIL: 输入处未找到 PDF 文件：%s\n" % args.input)
        return 2

    outdir = args.outdir if args.outdir else (
        os.path.dirname(os.path.abspath(pdfs[0])) if os.path.isfile(args.input)
        else args.input)
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    status_path = os.path.join(outdir, "extract_status.csv")

    used_names = set()
    statuses = []  # (源, 输出, 状态, 页数, 字符数, h2, 备注)
    n_bad = 0
    for pdf in pdfs:
        stem = os.path.splitext(os.path.basename(pdf))[0]
        md_name = stem + ".md"
        if md_name in used_names:  # 同名冲突（不同子目录同 stem）：前置父目录名消歧
            parent = os.path.basename(os.path.dirname(os.path.abspath(pdf)))
            md_name = "%s_%s" % (parent, md_name)
        used_names.add(md_name)
        md_path = os.path.join(outdir, md_name)
        try:
            if level == 1:
                md, pages = to_md_via_4llm(pdf), None
            elif level == 3:
                md, pages = to_md_via_markitdown(pdf), None
            else:
                md, pages = to_md_via_pymupdf(pdf)
            body = md.split("\n", 1)[1] if "\n" in md else ""
            if len(md) - len(stem) < MIN_CHARS or len(body.strip()) < MIN_CHARS:
                statuses.append((pdf, "", "NO_TEXT_LAYER", pages or 0, len(md), 0,
                                 "可提取文本过少，疑似扫描件/图片型 PDF，未写 .md"))
                n_bad += 1
                sys.stdout.write("NO_TEXT_LAYER  %s\n" % pdf)
                continue
            chars, h2 = len(md), h2_count(md)
            existed = os.path.isfile(md_path)
            if existed and not args.force:
                with open(md_path, "r", encoding="utf-8-sig") as f:
                    old = f.read()
                if old == md:
                    statuses.append((pdf, md_path, "SKIP_SAME", pages or 0, chars, h2,
                                     "目标已存在且内容一致，未重写"))
                    sys.stdout.write("SKIP_SAME     %s -> %s\n" % (pdf, md_name))
                    continue
                statuses.append((pdf, md_path, "SKIP_EXISTS", pages or 0, chars, h2,
                                 "目标已存在且内容不同，未覆盖（--force 可覆盖）"))
                sys.stdout.write("SKIP_EXISTS   %s -> %s\n" % (pdf, md_name))
                continue
            with open(md_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
            if existed:  # --force 覆盖（内容一致与否均执行写入）
                statuses.append((pdf, md_path, "OK_OVERWRITE", pages or 0, chars, h2, "--force 覆盖"))
                sys.stdout.write("OK_OVERWRITE  %s -> %s（%d 字符，%d 个二级题头）\n" % (pdf, md_name, chars, h2))
            else:
                statuses.append((pdf, md_path, "OK", pages or 0, chars, h2, ""))
                sys.stdout.write("OK            %s -> %s（%d 字符，%d 个二级题头）\n" % (pdf, md_name, chars, h2))
        except Exception as e:  # 单文件失败不中断批量
            statuses.append((pdf, "", "FAIL", 0, 0, 0, "%s: %s" % (type(e).__name__, e)))
            n_bad += 1
            sys.stdout.write("FAIL          %s（%s: %s）\n" % (pdf, type(e).__name__, e))

    with open(status_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["源文件", "输出文件", "状态", "页数", "字符数", "二级题头数", "备注"])
        for row in statuses:
            w.writerow([str(c) if c is not None else "" for c in row])
    engine_name = {1: "pymupdf4llm", 2: "pymupdf 轻量包装", 3: "markitdown"}[level]
    sys.stdout.write("提取级别：%s；共 %d 个 PDF，异常 %d 个；状态清单 → %s\n"
                     % (engine_name, len(pdfs), n_bad, status_path))
    return 1 if n_bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
