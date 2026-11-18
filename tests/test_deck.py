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


def test_deck_overview_visibility_rule_present(deck_plan):
    """静态守卫：总览可见性规则必须进产物 CSS。

    2026-11-18 bug 回归点：layoutOverview 平铺所有页的 transform，但 .vr-slide 默认
    display:none（仅 .vr-active 为 flex），缺 .vr-overview 规则时总览只剩当前页。
    """
    html = render_report(deck_plan)
    assert ".vr-overview .vr-slide" in html


def test_deck_overview_e2e_all_slides_visible(deck_plan, tmp_path):
    """总览 e2e：O 进总览所有页 computed display 不为 none，O 退出恢复单页。

    需 playwright（可选依赖，未装自动跳过）；静态守卫见上一条测试。
    """
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    out = tmp_path / "deck.html"
    out.write_text(render_report(deck_plan), encoding="utf-8")
    n = len(deck_plan["slides"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(out.as_uri())
            page.keyboard.press("o")
            assert page.eval_on_selector(".vr-deck", "e => e.classList.contains('vr-overview')")
            visible = page.eval_on_selector_all(
                ".vr-slide", "els => els.filter(e => getComputedStyle(e).display !== 'none').length")
            assert visible == n, f"总览可见 {visible}/{n} 页"
            page.keyboard.press("o")
            assert not page.eval_on_selector(".vr-deck", "e => e.classList.contains('vr-overview')")
            active = page.eval_on_selector_all(
                ".vr-slide", "els => els.filter(e => e.classList.contains('vr-active')).length")
            assert active == 1
        finally:
            browser.close()


def test_deck_passes_static_check(deck_plan, tmp_path):
    out = tmp_path / "deck.html"
    out.write_text(render_report(deck_plan), encoding="utf-8")
    result = inspect_html(out)
    assert result["status"] == "PASS", result


def test_deck_speaker_notes_in_panel(deck_plan):
    html = render_report(deck_plan)
    assert "开场 30 秒" in html          # 备注进面板
    assert html.count('data-note="cover"') == 2  # 面板条目 + 页内隐藏原文
