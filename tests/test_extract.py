"""素材解析器测试（标准库格式 + 数值列检测）。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from extract import _is_number, extract  # noqa: E402


def test_is_number():
    assert _is_number("128000")
    assert _is_number("3.2%")
    assert _is_number("-1.5")
    assert _is_number("1,290")
    assert not _is_number("2026-06")   # 日期不是数值
    assert not _is_number("华北")
    assert not _is_number("")


def test_extract_csv_detects_numeric_cols(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text(
        "月份,访问量,备注\n2026-06,1000,正常\n2026-07,1200,良好\n", encoding="utf-8"
    )
    out = tmp_path / "material.md"
    result = extract([csv_file], out)
    assert result["extracted"] == 1
    text = out.read_text(encoding="utf-8")
    numeric_line = text.split("数值列：")[-1].split("（")[0]
    assert "访问量" in numeric_line          # 数值列被识别
    assert "月份" not in numeric_line        # 日期列不应被标记为数值
    assert "备注" not in numeric_line        # 文本列不应被标记为数值


def test_extract_json_structure_summary(tmp_path):
    j = tmp_path / "kpi.json"
    j.write_text(json.dumps([{"a": 1}, {"a": 2}]), encoding="utf-8")
    out = tmp_path / "material.md"
    extract([j], out)
    text = out.read_text(encoding="utf-8")
    assert "JSON 数组" in text and "2 项" in text


def test_extract_md_passthrough(tmp_path):
    m = tmp_path / "note.md"
    m.write_text("# 标题\n\n正文", encoding="utf-8")
    out = tmp_path / "material.md"
    extract([m], out)
    assert "# 标题" in out.read_text(encoding="utf-8")


def test_extract_unsupported_and_missing_reported(tmp_path):
    out = tmp_path / "material.md"
    result = extract([tmp_path / "a.xyz", tmp_path / "missing.md"], out)
    assert result["failed"] == 2
    idx = json.loads(out.with_suffix(".index.json").read_text(encoding="utf-8"))
    assert len(idx["failures"]) == 2


def test_extract_directory_scans_supported_formats(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "sub" / "b.csv").write_text("x\n1\n", encoding="utf-8")
    (tmp_path / "sub" / ".hidden.md").write_text("hide", encoding="utf-8")  # 隐藏文件应跳过
    from extract import scan_dir
    result = extract(scan_dir(tmp_path / "sub"), tmp_path / "out" / "material.md")
    assert result["extracted"] == 2
