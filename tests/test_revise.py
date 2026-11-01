"""修订闭环测试：diff 映射、apply 成功/失败保留旧产物、回滚。"""

import json
import shutil
from pathlib import Path

import pytest

from visual_report.project import ReviseError, RevisionManager, diff_plans

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path):
    """搭建一个带产物与历史的项目工作区。"""
    plan = json.loads((FIXTURES / "smoke.json").read_text(encoding="utf-8"))
    plan_dir = tmp_path / "demo"
    plan_dir.mkdir()
    plan_path = plan_dir / "report-plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    from visual_report.render import render_report
    out = tmp_path / "output" / "visual-report.html"
    out.parent.mkdir()
    out.write_text(render_report(plan), encoding="utf-8")
    return plan_path, out, plan


def test_diff_maps_to_ids(workspace):
    _, _, plan = workspace
    new = json.loads(json.dumps(plan))
    new["sections"][1]["blocks"][0]["content"] = "改过的内容"
    new["sections"][2]["title"] = "新标题"
    d = diff_plans(plan, new)
    assert "sections{overview}/blocks{overview-intro}/content" in d["changed"]
    assert "sections{data}/title" in d["changed"]


def test_diff_detects_add_remove(workspace):
    _, _, plan = workspace
    new = json.loads(json.dumps(plan))
    new["sections"][1]["blocks"].append({"type": "text", "content": "新块"})
    d = diff_plans(plan, new)
    assert any("added" == k for k in d)
    assert any("blocks" in p for p in d["added"])


def test_apply_success_records_history(workspace):
    plan_path, out, plan = workspace
    mgr = RevisionManager(plan_path, out)

    # 首次 apply：无历史快照，作为基线版本（changedNodes 为 <初始版本>）
    baseline = mgr.apply("建立基线")
    assert baseline["version"] == 1
    assert baseline["changedNodes"] == ["<初始版本>"]
    assert (mgr.snap_dir / "v1-plan.json").is_file()

    # 二次 apply：对 plan 的修改被节点级 diff 捕获
    plan["sections"][1]["subtitle"] = "修订后的副标题"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    entry = mgr.apply("第一次修订")
    assert entry["version"] == 2
    assert "sections{overview}/subtitle" in entry["changedNodes"]
    assert mgr.load_revisions()["revisions"][-1]["description"] == "第一次修订"
    assert (mgr.snap_dir / "v1.html").is_file()  # 旧 HTML 已快照


def test_apply_failure_keeps_old_html(workspace):
    plan_path, out, plan = workspace
    old_html = out.read_text(encoding="utf-8")
    mgr = RevisionManager(plan_path, out)

    # 破坏 plan：非法主题 → 第一层校验失败
    plan["meta"]["theme"] = "broken"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ReviseError):
        mgr.apply("坏修订")

    assert out.read_text(encoding="utf-8") == old_html  # 旧产物原样保留
    assert mgr.load_revisions()["revisions"] == []       # 未记入历史


def test_rollback_restores_previous(workspace):
    plan_path, out, plan = workspace
    mgr = RevisionManager(plan_path, out)
    original_subtitle = plan["sections"][1].get("subtitle")

    plan["sections"][1]["subtitle"] = "v1 修改"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    mgr.apply("v1")

    plan["sections"][1]["subtitle"] = "v2 修改"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    mgr.apply("v2")

    result = mgr.rollback()  # 默认回滚到 v1
    assert result["rolledBackTo"] == 1
    restored = json.loads(plan_path.read_text(encoding="utf-8"))
    assert restored["sections"][1]["subtitle"] == "v1 修改"
    assert restored["sections"][1]["subtitle"] != original_subtitle
