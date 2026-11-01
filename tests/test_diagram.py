"""diagram 块测试：渲染 + 校验规则。"""

from visual_report.diagram import render_diagram
from visual_report.validate import validate_report


NODES = [
    {"id": "web", "label": "Web 前端", "at": [0, 0], "kind": "client"},
    {"id": "gw", "label": "API 网关", "at": [1, 0], "kind": "service"},
    {"id": "db", "label": "主库", "at": [2, 0], "kind": "storage"},
]
EDGES = [
    {"from": "web", "to": "gw", "label": "HTTPS"},
    {"from": "gw", "to": "db"},
]


def test_render_diagram_basic():
    svg = render_diagram(NODES, EDGES)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<rect") == 3          # 3 个节点
    assert svg.count("marker-end") == 2     # 2 条箭头边
    assert "HTTPS" in svg                   # 边标签


def test_render_diagram_escapes_labels():
    svg = render_diagram(
        [{"id": "x", "label": "<script>", "at": [0, 0]}], []
    )
    assert "<script>" not in svg


def test_render_diagram_wraps_long_labels():
    svg = render_diagram(
        [{"id": "x", "label": "这是一个非常长的节点标签需要自动换行", "at": [0, 0]}], []
    )
    assert svg.count("<text") >= 2  # 多行文本


def _plan_with_diagram(nodes, edges):
    return {
        "meta": {"title": "t", "theme": "minimal"},
        "sections": [{
            "id": "arch", "layout": "prose", "title": "架构",
            "blocks": [{"type": "diagram", "nodes": nodes, "edges": edges}],
        }],
    }


def test_validate_diagram_edge_reference():
    plan = _plan_with_diagram(NODES, [{"from": "web", "to": "ghost"}])
    errors = validate_report(plan)
    assert any("[diagram]" in e and "不存在的节点" in e for e in errors)


def test_validate_diagram_cell_collision():
    dup = dict(NODES[1], at=[0, 0])
    plan = _plan_with_diagram(NODES + [dup], EDGES)
    errors = validate_report(plan)
    assert any("同占网格" in e for e in errors)


def test_validate_diagram_duplicate_node_id():
    dup = dict(NODES[0], at=[5, 5], label="另一个")
    plan = _plan_with_diagram(NODES + [dup], EDGES)
    errors = validate_report(plan)
    assert any("节点 ID" in e and "重复" in e for e in errors)


def test_validate_diagram_ok():
    assert validate_report(_plan_with_diagram(NODES, EDGES)) == []
