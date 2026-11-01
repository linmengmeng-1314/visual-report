"""golden-file 渲染测试 + 静态检查测试。

golden 基准更新方式：
    UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_render.py
"""

import json
import os
from pathlib import Path

import pytest

from visual_report.render import render_report

import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from static_check import SIZE_LIMIT, inspect_html  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture
def rendered_html():
    plan = json.loads((FIXTURES / "smoke.json").read_text(encoding="utf-8"))
    return render_report(plan)


def test_render_deterministic(rendered_html, tmp_path):
    """相同输入两次渲染结果完全一致。"""
    plan = json.loads((FIXTURES / "smoke.json").read_text(encoding="utf-8"))
    assert render_report(plan) == rendered_html


def test_golden_file(rendered_html):
    golden_path = GOLDEN / "smoke.html"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        golden_path.write_text(rendered_html, encoding="utf-8")
        pytest.skip("golden 已更新")
    assert golden_path.exists(), "golden 基准缺失，先运行 UPDATE_GOLDEN=1 pytest 更新"
    assert rendered_html == golden_path.read_text(encoding="utf-8"), (
        "渲染结果与 golden 基准不一致（预期行为变化请用 UPDATE_GOLDEN=1 更新并 review diff）"
    )


def test_single_file_offline(rendered_html, tmp_path):
    """产物过第二层质检：无外部资源、无未内嵌 CSS/JS。"""
    out = tmp_path / "report.html"
    out.write_text(rendered_html, encoding="utf-8")
    result = inspect_html(out)
    assert result["status"] == "PASS", result


def test_static_check_catches_external_resource(tmp_path):
    bad = tmp_path / "bad.html"
    bad.write_text(
        '<html><head><link rel="stylesheet" href="https://cdn.example.com/a.css">'
        "</head><body><section id='s'>x</section></body></html>",
        encoding="utf-8",
    )
    result = inspect_html(bad)
    assert result["status"] == "FAILED"
    assert any("[offline]" in e for e in result["errors"])


def test_static_check_catches_size_limit(tmp_path, monkeypatch):
    import static_check
    monkeypatch.setattr(static_check, "SIZE_LIMIT", 10)  # 10 字节上限
    big = tmp_path / "big.html"
    big.write_text("<html><body>" + "x" * 100 + "</body></html>", encoding="utf-8")
    result = static_check.inspect_html(big)
    assert result["status"] == "FAILED"
    assert any("[size]" in e for e in result["errors"])
