#!/usr/bin/env python3
"""多格式素材解析器（Phase 4b）：把 DOCX/PDF/CSV/JSON/MD/TXT 提取为统一素材摘要。

定位：确定性提取（无 LLM）。产出两件东西——
  1. material.md      供 Agent 阅读的素材摘要（带来源标记），是内容规划的输入
  2. material-index.json  素材索引（路径/类型/哈希/概要），后续修订时判断是否需重读素材

格式支持：
  md/txt/csv/json  标准库，开箱即用
  docx             可选依赖 python-docx（pip install "visual-report[input]"）
  pdf              可选依赖 pypdf（同上；文本型 PDF，扫描件不支持并会明确提示）

用法：
    python scripts/extract.py 素材目录/ -o .visual-report/material.md
    python scripts/extract.py a.md b.csv c.docx -o .visual-report/material.md
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

# 中文 Windows 控制台重定向输出时按 GBK 编码，✓/✗ 等符号会触发 UnicodeEncodeError——统一切 UTF-8（Mac/Linux 已是 UTF-8，此段无操作）
for _s in (sys.stdout, sys.stderr):
    _rc = getattr(_s, "reconfigure", None)
    if _rc and getattr(_s, "encoding", "").lower().replace("-", "") != "utf8":
        _rc(encoding="utf-8")

MAX_TABLE_ROWS = 12          # 表格预览行数（超出截断并注明）
MAX_TEXT_CHARS = 8000        # 单文件文本上限（素材摘要不是全文搬运）
NUMERIC_SAMPLE = 8           # 数值列检测的采样行数


def _is_number(s: str) -> bool:
    """'128000'/'3.2%'/'-1.5' 是数值；'2026-06'（日期）不是。"""
    t = s.strip().rstrip("%").replace(",", "")
    if t.startswith("-"):
        t = t[1:]
    if not t or "-" in t:          # 内部连字符 = 日期/区间，不是数值
        return False
    return t.replace(".", "", 1).isdigit()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n…（原文 {len(text)} 字符，已截断至 {limit}）"


# ---- 各格式提取器：返回 (digest_markdown, summary) ----

def extract_md(path: Path):
    text = path.read_text(encoding="utf-8")
    return text, f"Markdown，{len(text)} 字符"


def extract_txt(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, f"纯文本，{len(text)} 字符"


def extract_csv(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return "（空 CSV）", "空文件"
    header, data = rows[0], rows[1:]

    # 数值列检测：采样前几行判断是否全为数字
    numeric_cols = []
    for ci in range(len(header)):
        sample = [r[ci] for r in data[:NUMERIC_SAMPLE] if ci < len(r)]
        if sample and all(_is_number(s) for s in sample):
            numeric_cols.append(header[ci])

    lines = [f"| {' | '.join(header)} |", f"|{'|'.join(['---'] * len(header))}|"]
    for r in data[:MAX_TABLE_ROWS]:
        lines.append(f"| {' | '.join(r)} |")
    if len(data) > MAX_TABLE_ROWS:
        lines.append(f"\n…共 {len(data)} 行数据，预览前 {MAX_TABLE_ROWS} 行")

    digest = "\n".join(lines)
    if numeric_cols:
        digest += f"\n\n数值列：{', '.join(numeric_cols)}（适合做图表）"
    summary = f"CSV，{len(data)} 行 × {len(header)} 列" + (f"，数值列 {len(numeric_cols)} 个" if numeric_cols else "")
    return digest, summary


def extract_json(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            keys = sorted({k for item in data[:50] for k in item})
            digest = f"JSON 数组，{len(data)} 项。字段：{', '.join(keys)}\n\n首项预览：\n```json\n{json.dumps(data[0], ensure_ascii=False, indent=2)[:1500]}\n```"
        else:
            digest = f"JSON 数组，{len(data)} 项：\n```json\n{json.dumps(data[:10], ensure_ascii=False)[:1500]}\n```"
        return digest, f"JSON 数组，{len(data)} 项"
    if isinstance(data, dict):
        keys = list(data.keys())
        digest = f"JSON 对象，顶层字段：{', '.join(keys[:30])}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}\n```"
        return digest, f"JSON 对象，{len(keys)} 个顶层字段"
    return json.dumps(data, ensure_ascii=False)[:1500], "JSON 标量"


def extract_docx(path: Path):
    try:
        import docx
    except ImportError:
        return None, "需要可选依赖：pip install python-docx（或 pip install \"visual-report[input]\"）"
    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for t_i, table in enumerate(doc.tables):
        rows = [[c.text.strip() for c in row.cells] for row in table.rows]
        if rows:
            parts.append(f"\n[表格 {t_i + 1}]\n| {' | '.join(rows[0])} |\n|{'|'.join(['---'] * len(rows[0]))}|")
            parts.extend(f"| {' | '.join(r)} |" for r in rows[1:MAX_TABLE_ROWS])
    text = "\n\n".join(parts)
    return _clip(text), f"DOCX，{len(doc.paragraphs)} 段 + {len(doc.tables)} 表"


def extract_pdf(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "需要可选依赖：pip install pypdf（或 pip install \"visual-report[input]\"）"
    reader = PdfReader(str(path))
    texts = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        if t.strip():
            texts.append(f"--- 第 {i + 1} 页 ---\n{t.strip()}")
    if not texts:
        return None, "PDF 无可提取文本（可能是扫描件，请改用其他素材或 OCR 后提供）"
    return _clip("\n\n".join(texts)), f"PDF，{len(reader.pages)} 页（文本型）"


EXTRACTORS = {
    ".md": extract_md, ".markdown": extract_md, ".txt": extract_txt,
    ".csv": extract_csv, ".json": extract_json,
    ".docx": extract_docx, ".pdf": extract_pdf,
}


def extract(paths: list, output: Path) -> dict:
    index, digests, failures = [], [], []

    for p in paths:
        ext = p.suffix.lower()
        extractor = EXTRACTORS.get(ext)
        if extractor is None:
            failures.append({"path": str(p), "reason": f"不支持的格式 {ext}（支持：{'/'.join(EXTRACTORS)}）"})
            continue
        if not p.is_file():
            failures.append({"path": str(p), "reason": "文件不存在"})
            continue
        digest, summary = extractor(p)
        if digest is None:
            failures.append({"path": str(p), "reason": summary})
            continue
        digests.append(f"## 来源：`{p}`\n\n> {summary}\n\n{digest}")
        index.append({"path": str(p), "type": ext.lstrip("."), "sha256_16": _hash(p), "summary": summary})

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# 素材摘要（extract.py 自动生成，供内容规划使用）\n\n" + "\n\n---\n\n".join(digests),
        encoding="utf-8",
    )
    index_path = output.with_suffix(".index.json")
    index_path.write_text(
        json.dumps({"materials": index, "failures": failures}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"extracted": len(index), "failed": len(failures), "material": str(output), "index": str(index_path)}


def scan_dir(directory: Path) -> list:
    """递归扫描目录内受支持的格式（跳过隐藏文件/目录）。"""
    return sorted(
        f for f in directory.rglob("*")
        if f.suffix.lower() in EXTRACTORS
        and not any(part.startswith(".") for part in f.parts)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="多格式素材 → 统一素材摘要")
    parser.add_argument("inputs", nargs="+", help="文件或目录（目录递归扫描支持的格式）")
    parser.add_argument("-o", "--output", default=".visual-report/material.md", help="素材摘要输出路径")
    args = parser.parse_args()

    paths = []
    for i in args.inputs:
        p = Path(i)
        paths.extend(scan_dir(p) if p.is_dir() else [p])

    result = extract(paths, Path(args.output))
    print(f"✓ 提取 {result['extracted']} 个文件 → {result['material']}")
    print(f"  素材索引 → {result['index']}")
    if result["failed"]:
        print(f"⚠ {result['failed']} 个文件未解析：", file=sys.stderr)
        idx = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
        for f in idx["failures"]:
            print(f"  - {f['path']}: {f['reason']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
