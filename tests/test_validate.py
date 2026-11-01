"""第一层质检测试：Schema 用例集（含失败用例，借鉴 failure-fixtures 思路）。"""

import json
import copy
from pathlib import Path

import pytest

from visual_report.validate import validate_report

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def good_plan():
    return json.loads((FIXTURES / "smoke.json").read_text(encoding="utf-8"))


def test_valid_plan_passes(good_plan):
    assert validate_report(good_plan) == []


def test_invalid_theme_rejected(good_plan):
    good_plan["meta"]["theme"] = "dark-neon"
    errors = validate_report(good_plan)
    assert any("theme" in e for e in errors)


def test_invalid_id_format_rejected(good_plan):
    good_plan["sections"][1]["id"] = "Bad_ID"
    errors = validate_report(good_plan)
    # schema pattern 与 [id] 专项检查双层兜底，任一层拦截即可
    assert any("Bad_ID" in e for e in errors)


def test_duplicate_section_id_rejected(good_plan):
    good_plan["sections"][2]["id"] = good_plan["sections"][1]["id"]
    errors = validate_report(good_plan)
    assert any("重复" in e for e in errors)


def test_external_image_rejected(good_plan):
    good_plan["sections"][1]["blocks"].append(
        {"type": "image", "src": "https://cdn.example.com/logo.png"}
    )
    errors = validate_report(good_plan)
    assert any("[offline]" in e for e in errors)


def test_chart_series_misalignment_rejected(good_plan):
    blk = copy.deepcopy(good_plan["sections"][2]["blocks"][1])  # line chart
    blk["data"]["series"][0]["values"] = [1, 2]  # 2 个值 vs 8 个 label
    good_plan["sections"][2]["blocks"].append(blk)
    errors = validate_report(good_plan)
    assert any("[chart]" in e and "不对齐" in e for e in errors)


def test_unknown_layout_rejected(good_plan):
    good_plan["sections"][1]["layout"] = "fancy-3d"
    errors = validate_report(good_plan)
    assert any("layout" in e for e in errors)


def test_missing_title_rejected(good_plan):
    del good_plan["meta"]["title"]
    errors = validate_report(good_plan)
    assert errors != []
