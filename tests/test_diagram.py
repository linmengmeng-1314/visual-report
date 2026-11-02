"""diagram 块测试：渲染 + 校验规则。"""

import re

from visual_report.diagram import render_diagram
from visual_report.render import render_report
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


def test_multi_diagram_marker_ids_unique():
    """回归：同页多图的 marker id 由块 ID 派生，全页唯一（曾致 static_check dup-id FAILED）。"""
    plan = _plan_with_diagram(NODES, EDGES)
    plan["sections"][0]["blocks"] = [
        {"id": "d1", "type": "diagram", "nodes": NODES, "edges": EDGES},
        {"id": "d2", "type": "diagram", "nodes": NODES, "edges": EDGES},
    ]
    html = render_report(plan)
    assert re.findall(r'<marker id="([^"]+)"', html) == ["vr-arrow-d1", "vr-arrow-d2"]
    assert html.count("url(#vr-arrow-d1)") == len(EDGES)  # 每张图只引用自己的 marker


def test_diagram_marker_id_fallback_without_block_id():
    """块无 ID（schema 允许省略）时以「容器 ID + 块序」兜底，同页多图仍唯一且确定。"""
    plan = _plan_with_diagram(NODES, EDGES)
    plan["sections"][0]["blocks"].append({"type": "diagram", "nodes": NODES, "edges": EDGES})
    html = render_report(plan)
    assert re.findall(r'<marker id="([^"]+)"', html) == ["vr-arrow-arch-0", "vr-arrow-arch-1"]


# ---- diagram 2.0：正交圆角布线 / crossover halo / 几何 lint ------------------

from visual_report.diagram import direction_warnings, lint_diagram, plan_diagram


def test_direction_warnings_vertical_chain_in_lr():
    """B1：lr 声明 + 纵向主链 → 建议级提示；tb 下同布局合法，水平主链不误报。"""
    vertical = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "b", "label": "B", "at": [0, 1]},
        {"id": "c", "label": "C", "at": [0, 2]},
    ]
    chain = [{"from": f, "to": t} for f, t in (("a", "b"), ("b", "c"))]
    assert direction_warnings(vertical, chain, "lr"), "纵向主链塞 lr 应提示"
    assert not direction_warnings(vertical, chain, "tb"), "tb 下同布局合法"
    assert not direction_warnings(NODES, EDGES, "lr"), "水平主链不误报"


def test_width_warnings_over_budget():
    """图宽超栏宽 → 建议级提示（等比缩放会让文字变小，优先纵向重排而非横滑）。"""
    from visual_report.diagram import width_warnings
    nodes5 = [{"id": f"n{i}", "label": "节点", "at": [i, 0]} for i in range(5)]  # ~1028px
    assert width_warnings(nodes5, wide=False), "5 列约 1028px 超 860 栏宽应提示"
    assert not width_warnings(nodes5, wide=True), "wide 版栏宽 1100px 内不提示"
    nodes4 = [{"id": f"n{i}", "label": "节点", "at": [i, 0]} for i in range(4)]  # ~832px
    assert not width_warnings(nodes4, wide=False), "4 列约 832px 在栏宽内"


# ---- 第五波：胶囊 vs 胶囊、文字 vs 自身盒子（统一碰撞集收口） ---------------

from visual_report.diagram import (  # noqa: E402
    NODE_TEXT_MAXW, _rect_overlaps_rect, _text_width, _wrap_label,
)


def test_edge_labels_never_overlap_each_other():
    """复现件 A：共享源节点的两条边，标签胶囊不得互压（placed 注册表收口）。"""
    nodes = [
        {"id": "src", "label": "源节点", "at": [0, 0]},
        {"id": "m", "label": "主库", "at": [2, 0]},
        {"id": "au", "label": "审计库", "at": [2, 1]},
    ]
    edges = [
        {"from": "src", "to": "m", "label": "MyBatis-Plus 读写"},
        {"from": "src", "to": "au", "label": "audit 全链路"},
    ]
    rects = [l["rect"] for l in plan_diagram(nodes, edges)["labels"].values()]
    assert len(rects) == 2
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not _rect_overlaps_rect(rects[i], rects[j], 2), f"标签 {i} 与 {j} 重叠"


def test_node_label_wraps_by_measured_width():
    """复现件 B：显式 \\n 行内超宽需按实测宽度二次断行（宽度模型，非字符数）。"""
    lines = _wrap_label("Redis\n操作人真名缓存 2h/15min")
    assert lines[0] == "Redis"
    for ln in lines:
        assert _text_width(ln, 14) <= NODE_TEXT_MAXW, f"行超宽：{ln!r}"


def test_lint_node_text_overflow():
    """超框 lint：分行后仍超盒高行数的标签被拦（旧实现静默截断丢信息）。"""
    nodes = [{"id": "cfg", "label": "操作人真实姓名缓存与审计策略中心 dev/test/prod", "at": [0, 0]}]
    issues = lint_diagram(nodes, [])
    assert any("文字超框" in i for i in issues)


# ---- 边标签几何（用户实测反馈：胶囊压箭头线；短段时压两端节点盒） ----------

from visual_report.diagram import _boxes_for, plan_diagram


def test_edge_label_never_overlaps_nodes_on_short_segment():
    """邻列短段 + 宽胶囊：应落到行间走廊，而不是压到两端节点盒。"""
    nodes = [
        {"id": "a", "label": "步骤一", "at": [0, 0]},
        {"id": "b", "label": "步骤二", "at": [1, 0]},
    ]
    edges = [{"from": "a", "to": "b", "label": "消费消息"}]  # 胶囊 58px > 间隙可用宽度
    plan = plan_diagram(nodes, edges)
    (lab,) = plan["labels"].values()
    r = lab["rect"]
    for b in _boxes_for(nodes).values():
        assert not (r["x"] - 2 < b["x"] + 136 and r["x"] + r["w"] + 2 > b["x"]
                    and r["y"] - 2 < b["y"] + 62 and r["y"] + r["h"] + 2 > b["y"]), \
            f"标签胶囊压到节点 {b['id']}"


def test_edge_label_lifted_above_line():
    """胶囊放线上时抬高：底边与箭头线保持 ≥2px 间隙，描边不压线。"""
    nodes = [
        {"id": "a", "label": "A", "at": [0, 0]},
        {"id": "b", "label": "B", "at": [2, 0]},  # 隔一格，段足够长
    ]
    plan = plan_diagram(nodes, [{"from": "a", "to": "b", "label": "HTTPS"}])
    (lab,) = plan["labels"].values()
    line_y = _boxes_for(nodes)["a"]["cy"]
    assert lab["anchor"] == "middle"
    assert lab["rect"]["y"] + lab["rect"]["h"] <= line_y - 2, "胶囊底边应高于箭头线 2px 以上"


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
