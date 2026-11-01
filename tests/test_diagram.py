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
    assert svg.count('data-node-id') == 3   # 3 个节点（可聚焦）
    assert svg.count("marker-end") == 2     # 2 条箭头边
    assert "HTTPS" in svg                   # 边标签
    assert 'rx="7"' in svg                  # 标签胶囊底衬（借鉴 archify）


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


def test_render_diagram_animated_flow():
    """animated=true 时输出流光覆盖线，且带错峰延迟；默认不输出。"""
    static_svg = render_diagram(NODES, EDGES)
    assert "vr-edge-flow" not in static_svg
    animated_svg = render_diagram(NODES, EDGES, animated=True)
    assert animated_svg.count("vr-edge-flow") == len(EDGES)
    assert "animation-delay" in animated_svg


# ---- diagram 2.0：正交圆角布线 / crossover halo / 几何 lint ------------------

from visual_report.diagram import lint_diagram, plan_diagram


def test_diagram_orthogonal_straight_edge():
    """同行相邻格：直线（无拐点），path 形式输出。"""
    p = plan_diagram(NODES, EDGES)
    pts = p["routes"][0][1]  # web -> gw
    assert len(pts) == 2 and pts[0][1] == pts[1][1]  # 水平直线
    svg = render_diagram(NODES, EDGES)
    assert '<path class="vr-edge-base"' in svg


def test_diagram_orthogonal_elbow_rounded():
    """斜向相邻格：elbow 折线 + Q 贝塞尔圆角转角。"""
    nodes = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "b", "label": "B", "at": [1, 1]},
    ]
    p = plan_diagram(nodes, [{"from": "a", "to": "b"}])
    pts = p["routes"][0][1]
    assert 3 <= len(pts) <= 4          # 1~2 个拐角的折线
    assert all(abs(pts[i][0] - pts[i + 1][0]) < 1 or abs(pts[i][1] - pts[i + 1][1]) < 1
               for i in range(len(pts) - 1))  # 每段水平或垂直
    svg = render_diagram(nodes, [{"from": "a", "to": "b"}])
    assert "Q " in svg                 # 圆角转角


def test_diagram_port_spread_shared_side():
    """同节点同侧两条边：端点错开（port spread），不再是同一点。"""
    nodes = [
        {"id": "hub", "label": "Hub", "at": [1, 0]},
        {"id": "x", "label": "X", "at": [0, 0]},
        {"id": "y", "label": "Y", "at": [0, 1]},
    ]
    edges = [{"from": "x", "to": "hub"}, {"from": "y", "to": "hub"}]
    p = plan_diagram(nodes, edges)
    ys = {round(p["routes"][i][1][-1][1], 1) for i in (0, 1)}  # hub 侧端点 y
    assert len(ys) == 2                # 两条边在 hub 左侧错开
    assert lint_diagram(nodes, edges) == []


def test_diagram_reverse_edges_parallel_lanes():
    """反向边 A↔B：两条平行走线，不共线重叠。"""
    nodes = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "b", "label": "B", "at": [1, 0]},
    ]
    edges = [{"from": "a", "to": "b", "label": "请求"}, {"from": "b", "to": "a", "label": "响应"}]
    p = plan_diagram(nodes, edges)
    lane_a = p["routes"][0][1]
    lane_b = p["routes"][1][1]
    assert abs(lane_a[0][1] - lane_b[0][1]) >= 8   # 错开两条车道
    assert lint_diagram(nodes, edges) == []


def test_diagram_crossover_halo():
    """不可避免的两边交叉：后绘制的边在交点垫背景色粗线（跨线跳桥）。"""
    nodes = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "b", "label": "B", "at": [1, 1]},
        {"id": "c", "label": "C", "at": [1, 0]},
        {"id": "d", "label": "D", "at": [0, 1]},
    ]
    edges = [{"from": "a", "to": "b"}, {"from": "c", "to": "d"}]
    plan = plan_diagram(nodes, edges)
    assert plan["halos"], "X 形布局应产生交叉 halo"
    svg = render_diagram(nodes, edges)
    assert 'class="vr-edge-halo"' in svg
    assert svg.count('class="vr-edge-halo"') == sum(len(v) for v in plan["halos"].values())
    assert lint_diagram(nodes, edges) == []


def test_diagram_lint_detects_through_box():
    """穿盒检测原语：线段穿过盒子（含 2px 间隙）时报 True。"""
    from visual_report.diagram import _seg_intersects_rect
    box = {"x": 100, "y": 100, "w": 60, "h": 40}
    assert _seg_intersects_rect((80, 120), (200, 120), box)          # 横穿
    assert _seg_intersects_rect((130, 90), (130, 150), box)          # 竖穿
    assert _seg_intersects_rect((80, 120), (99, 120), box, 2)       # 2px 间隙内
    assert not _seg_intersects_rect((80, 120), (97, 120), box, 2)    # 间隙外
    assert not _seg_intersects_rect((80, 90), (200, 90), box, 2)     # 上方掠过


def test_diagram_avoids_blocker_same_row():
    """长边跳格且中间格被占：绕行走行间走廊，不穿盒。"""
    nodes = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "block", "label": "B", "at": [1, 0]},
        {"id": "c", "label": "C", "at": [2, 0]},
    ]
    edges = [{"from": "a", "to": "c"}]
    assert lint_diagram(nodes, edges) == []


def test_diagram_avoids_blocker_same_column():
    """同列跳格且中间格被占：从侧面绕行。"""
    nodes = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "block", "label": "B", "at": [0, 1]},
        {"id": "c", "label": "C", "at": [0, 2]},
    ]
    edges = [{"from": "a", "to": "c"}]
    assert lint_diagram(nodes, edges) == []


def test_diagram_dense_grid_matrix():
    """3×2 全占网格的 X 交叉 + 垂直边组合：全部 lint 通过（边角情况矩阵）。"""
    nodes = [{"id": f"n{c}{r}", "label": f"N{c}{r}", "at": [c, r]}
             for c in range(3) for r in range(2)]
    edges = [
        {"from": "n00", "to": "n21"},
        {"from": "n01", "to": "n20"},
        {"from": "n10", "to": "n11"},
        {"from": "n00", "to": "n01"},
        {"from": "n20", "to": "n21", "label": "同步"},
        {"from": "n00", "to": "n20", "label": "事件流"},
    ]
    issues = lint_diagram(nodes, edges)
    assert issues == []


def test_diagram_full_row_fan_out():
    """同行多边扇出：hub 向左右两侧各连多条，端口错开且 lint 全绿。"""
    nodes = [{"id": "hub", "label": "Hub", "at": [1, 0]},
             {"id": "l1", "label": "L1", "at": [0, 0]},
             {"id": "r1", "label": "R1", "at": [2, 0]},
             {"id": "r2", "label": "R2", "at": [2, 1]}]
    edges = [{"from": "l1", "to": "hub"},
             {"from": "hub", "to": "r1"},
             {"from": "hub", "to": "r2"},
             {"from": "r2", "to": "hub"}]
    assert lint_diagram(nodes, edges) == []


def test_validate_diagram_self_loop_rejected():
    plan = _plan_with_diagram(NODES, [{"from": "web", "to": "web"}])
    errors = validate_report(plan)
    assert any("自环" in e for e in errors)


def test_validate_diagram_lint_wired_into_gate():
    """几何 lint 接入第一层质检：合法图无诊断（空列表即通过）。"""
    assert validate_report(_plan_with_diagram(NODES, EDGES)) == []


def test_render_diagram_animated_uses_path():
    """流光覆盖线跟随折线路径。"""
    nodes = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "b", "label": "B", "at": [1, 1]},
    ]
    svg = render_diagram(nodes, [{"from": "a", "to": "b"}], animated=True)
    assert svg.count("vr-edge-flow") == 1
    base_d = svg.split('class="vr-edge-base" d="')[1].split('"')[0]
    flow_d = svg.split('class="vr-edge-flow" d="')[1].split('"')[0]
    assert base_d == flow_d          # 流光线与主线同路径
