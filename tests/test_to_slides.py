"""报告 → 幻灯片转换测试。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from to_slides import transform  # noqa: E402
from visual_report.validate import validate_plan  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def report():
    return json.loads((FIXTURES / "smoke.json").read_text(encoding="utf-8"))


def test_transform_produces_valid_deck(report):
    deck = transform(report)
    assert validate_plan(deck) == []
    layouts = [s["layout"] for s in deck["slides"]]
    assert layouts[0] == "title"          # hero → title
    assert "statement" in layouts         # conclusion → statement


def test_transform_reuses_chart_blocks(report):
    deck = transform(report)
    chart_slides = [s for s in deck["slides"] if s["layout"] == "chart"]
    assert chart_slides, "报告里的 chart 块应直接复用为 chart 页"
    reused_ids = {b["id"] for s in chart_slides for b in s["blocks"]}
    assert reused_ids & {"data-bar", "data-line", "data-donut"}


def test_transform_no_id_collision(report):
    """slide ID 不得与复用 block 的原 ID 撞名（转换器曾犯过的错）。"""
    deck = transform(report)
    all_ids = [s["id"] for s in deck["slides"]]
    all_ids += [b["id"] for s in deck["slides"] for b in s.get("blocks", []) if b.get("id")]
    assert len(all_ids) == len(set(all_ids))
    assert validate_plan(deck) == []


def test_transform_text_becomes_notes_and_bullets(report):
    deck = transform(report)
    bullets = [s for s in deck["slides"] if s["layout"] == "bullets"]
    if bullets:  # smoke 报告 hero 后第一段是 text
        assert bullets[0].get("notes"), "正文应降级为演讲备注供 Agent 精炼"
