"""幻灯片模式测试：Schema 路由、渲染、运行时、备注隐藏。"""

import json
import sys
from pathlib import Path

import pytest

from visual_report.validate import validate_plan, validate_slide
from visual_report.render import render_report

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from static_check import inspect_html  # noqa: E402

DECK = REPO / "examples" / "demo-deck" / "slide-plan.json"


@pytest.fixture
def deck_plan():
    return json.loads(DECK.read_text(encoding="utf-8"))


def test_validate_plan_routes_slides(deck_plan):
    assert validate_plan(deck_plan) == []


def test_validate_slide_catches_bad_layout(deck_plan):
    deck_plan["slides"][1]["layout"] = "fancy-3d"
    errors = validate_slide(deck_plan)
    assert any("layout" in e for e in errors)


def test_validate_slide_catches_duplicate_slide_id(deck_plan):
    deck_plan["slides"][2]["id"] = deck_plan["slides"][1]["id"]
    errors = validate_slide(deck_plan)
    assert any("重复" in e for e in errors)


def test_render_deck_deterministic(deck_plan):
    a = render_report(deck_plan)
    b = render_report(json.loads(DECK.read_text(encoding="utf-8")))
    assert a == b


def test_deck_runtime_present(deck_plan):
    html = render_report(deck_plan)
    assert "vr-deck" in html
    assert "vr-slide" in html
    # 运行时关键能力：键盘、全屏、总览、备注
    for key in ("ArrowRight", "ArrowLeft", "requestFullscreen", "layoutOverview", "vr-notes"):
        assert key in html
    # 备注原文必须被隐藏（视觉评审教训：泄漏到画面）
    assert ".vr-note-text { display: none; }" in html


def test_deck_passes_static_check(deck_plan, tmp_path):
    out = tmp_path / "deck.html"
    out.write_text(render_report(deck_plan), encoding="utf-8")
    result = inspect_html(out)
    assert result["status"] == "PASS", result


def test_deck_speaker_notes_in_panel(deck_plan):
    html = render_report(deck_plan)
    assert "开场 30 秒" in html          # 备注进面板
    assert html.count('data-note="cover"') == 2  # 面板条目 + 页内隐藏原文
