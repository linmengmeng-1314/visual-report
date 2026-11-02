"""构建期 SVG 流程/架构图（ADR-005，参考 ve-flow 的网格坐标声明式设计）。

节点用 "at": [col, row] 网格坐标声明，边用节点 ID 引用；
Renderer 负责布局、布线和箭头，AI 不需要算坐标。

diagram 2.0（借鉴 archify 的 routing/geometry，按网格布局大幅简化）：
- 正交圆角布线：边是 elbow 折线（Q 贝塞尔 8px 圆角转角），首末段垂直于出入侧；
  同节点同侧的多条边错开端点（port spread）
- 冲突感知：候选路由避开不相关节点盒，且不与已布边共线重叠/T 形相触
  （真正的交叉是允许的，由 crossover halo 垫出"跨线跳桥"）
- 几何 lint：穿盒 / 标签与线间距 / 拐点数 / 最短线段自检（lint_diagram，接入第一层质检）
"""

import html
import math
from typing import Dict, List, Optional, Tuple

CW, CH = 196, 96          # 网格单元尺寸（间隙需容纳边标签）
BOX_W, BOX_H = 136, 62    # 节点盒尺寸
PAD = 24

GUTTER = 16               # port spread 距侧边两端的留白
MAX_PORT_SPACING = 14     # 共享侧端点的最大错开间距
ALIGN_DELTA = 16          # 面向侧锚点偏差小于此值时对齐成直线
CORNER_R = 8              # 折线圆角半径
MIN_SEGMENT = 8           # 最短线段（= 圆角半径，保证拐角画得出）
MAX_BENDS = 3             # 每条边最多拐点数（lint 门禁）
BOX_CLEARANCE = 2         # 边与不相关节点盒的最小间隙
LABEL_CLEARANCE = 2       # 标签胶囊与不相关边的最小间隙
OVERLAP_MIN = 8           # 共线重叠超过此长度视为冲突
HALO_HALF = 8             # 交叉垫线半长
HALO_WIDTH = 6            # 交叉垫线宽度（≈ 4 × 1.5 线宽）
EPS = 1e-4

# kind → 视觉样式（描边色 + 线型），未声明的 kind 用默认样式
# 节点填充用 color-mix 从描边色派生淡色调（借鉴 archify 的 token 体系，深浅主题通吃）
KIND_STYLE = {
    "client":   ("var(--chart-6)", "solid"),
    "service":  ("var(--chart-1)", "solid"),
    "storage":  ("var(--chart-3)", "dashed"),
    "queue":    ("var(--chart-4)", "dashed"),
    "external": ("var(--text-2)",  "dotted"),
}
DEFAULT_STYLE = ("var(--border)", "solid")

FS_LABEL = 12  # 边标签字号

_OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
_SIDE_ORDER = ("right", "bottom", "left", "top")
# 出入方向符号：source 沿 side 向外，target 垂直于 side 进入
_SIDE_SIGN = {
    "left":   (-1, 1), "right": (1, -1),
    "top":    (-1, 1), "bottom": (1, -1),
}


def _text_width(s: str, fs: int = FS_LABEL) -> float:
    """CJK 每字约 1em，ASCII 约 0.62em。"""
    return sum(fs if ord(c) > 0x2e7f else fs * 0.62 for c in s)


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


# 架构图聚焦交互（报告与 deck 共用，借鉴 archify focus）：
# 悬浮节点 → 它与相邻边点亮、其余压暗；移开恢复；点击固定/解除。
FOCUS_JS = """(function(){
  function installDiagramFocus(){
    var pinned = null;
    function applyFocus(id){
      document.querySelectorAll('svg [data-node-id], svg [data-edge-from]').forEach(function(el){
        var on;
        if (el.hasAttribute('data-node-id')) {
          on = id && el.getAttribute('data-node-id') === id;
        } else {
          on = id && (el.getAttribute('data-edge-from') === id || el.getAttribute('data-edge-to') === id);
        }
        el.classList.toggle('vr-diagram-dim', id && !on);
        el.classList.toggle('vr-diagram-on', !!on);
      });
    }
    document.addEventListener('mouseover', function(e){
      var node = e.target.closest('[data-node-id]');
      if (node) applyFocus(node.getAttribute('data-node-id'));
    });
    document.addEventListener('mouseout', function(e){
      if (e.target.closest && e.target.closest('[data-node-id]')) {
        applyFocus(pinned);  // 恢复到固定态（无固定则全亮）
      }
    });
    document.addEventListener('click', function(e){
      var node = e.target.closest('[data-node-id]');
      if (!node) return;
      var id = node.getAttribute('data-node-id');
      pinned = (pinned === id) ? null : id;
      applyFocus(pinned || id);  // 点击即固定当前高亮；再点同节点解除
      if (!pinned) applyFocus(null);
    });
  }
  installDiagramFocus();
})();"""


def _wrap_label(label: str, width: int = 9) -> List[str]:
    """CJK 友好的标签换行：显式 \\n 优先，其次按宽度截断，最多 3 行。"""
    if "\n" in label:
        lines = label.split("\n")
    else:
        lines = [label[i:i + width] for i in range(0, len(label), width)]
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][: width - 1] + "…"
    return lines


# ---------------------------------------------------------------------------
# 几何原语（移植自 archify shared/geometry.mjs，纯函数）
# ---------------------------------------------------------------------------

def _cross3(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _proper_intersection(a, b, c, d) -> Optional[Tuple[float, float]]:
    """严格相交（端点相触不算），返回交点或 None。交叉 halo 与共线判定的基础。"""
    ab_c, ab_d = _cross3(a, b, c), _cross3(a, b, d)
    cd_a, cd_b = _cross3(c, d, a), _cross3(c, d, b)

    def opposite(l, r):
        return (l > EPS and r < -EPS) or (l < -EPS and r > EPS)

    if not opposite(ab_c, ab_d) or not opposite(cd_a, cd_b):
        return None
    denom = (a[0] - b[0]) * (c[1] - d[1]) - (a[1] - b[1]) * (c[0] - d[0])
    if abs(denom) < EPS:
        return None
    ab = a[0] * b[1] - a[1] * b[0]
    cd = c[0] * d[1] - c[1] * d[0]
    return ((ab * (c[0] - d[0]) - (a[0] - b[0]) * cd) / denom,
            (ab * (c[1] - d[1]) - (a[1] - b[1]) * cd) / denom)


def _orient(a, b, c) -> int:
    v = _cross3(a, b, c)
    if abs(v) < 1e-4:
        return 0
    return 1 if v > 0 else 2


def _on_segment(a, b, c) -> bool:
    return (b[0] <= max(a[0], c[0]) + EPS and b[0] >= min(a[0], c[0]) - EPS
            and b[1] <= max(a[1], c[1]) + EPS and b[1] >= min(a[1], c[1]) - EPS)


def _segments_touch(a, b, c, d) -> bool:
    """相交或相触（含端点），用于线段 vs 盒子边。"""
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(a, c, b):
        return True
    if o2 == 0 and _on_segment(a, d, b):
        return True
    if o3 == 0 and _on_segment(c, a, d):
        return True
    if o4 == 0 and _on_segment(c, b, d):
        return True
    return False


def _in_box(p, x1, y1, x2, y2) -> bool:
    return x1 <= p[0] <= x2 and y1 <= p[1] <= y2


def _seg_intersects_rect(a, b, box: dict, gap: float = 0.0) -> bool:
    """线段是否碰到（外扩 gap 的）矩形。"""
    x1, y1 = box["x"] - gap, box["y"] - gap
    x2, y2 = box["x"] + box["w"] + gap, box["y"] + box["h"] + gap
    if _in_box(a, x1, y1, x2, y2) or _in_box(b, x1, y1, x2, y2):
        return True
    corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    return any(_segments_touch(a, b, corners[i], corners[(i + 1) % 4]) for i in range(4))


def _collinear_overlap(a1, a2, b1, b2) -> float:
    """两条共线（同水平/垂直）线段的重叠长度，不共线返回 0。"""
    if abs(a1[1] - a2[1]) <= EPS and abs(b1[1] - b2[1]) <= EPS and abs(a1[1] - b1[1]) <= EPS:
        lo = max(min(a1[0], a2[0]), min(b1[0], b2[0]))
        hi = min(max(a1[0], a2[0]), max(b1[0], b2[0]))
        return max(0.0, hi - lo)
    if abs(a1[0] - a2[0]) <= EPS and abs(b1[0] - b2[0]) <= EPS and abs(a1[0] - b1[0]) <= EPS:
        lo = max(min(a1[1], a2[1]), min(b1[1], b2[1]))
        hi = min(max(a1[1], a2[1]), max(b1[1], b2[1]))
        return max(0.0, hi - lo)
    return 0.0


def _point_strictly_inside(p, seg) -> bool:
    """点是否在线段的严格内域（共线且不与端点重合）。"""
    a, b = seg
    if abs(_cross3(a, b, p)) > EPS * (math.hypot(b[0] - a[0], b[1] - a[1]) + 1):
        return False
    return (min(a[0], b[0]) + EPS < p[0] < max(a[0], b[0]) - EPS
            or min(a[1], b[1]) + EPS < p[1] < max(a[1], b[1]) - EPS)


def _orthogonal_touch(cand, other) -> bool:
    """T 形搭线：一方的端点落在另一方线段的严格内域——视觉上像分叉，按冲突处理。

    注意正常穿越（交点在双方内域、四端都不相触）不算，那由 crossover halo 解决。
    """
    return (any(_point_strictly_inside(p, other) for p in cand)
            or any(_point_strictly_inside(p, cand) for p in other))


def _normalize_points(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """去掉重复点与前向共线的中间点（拐角只在真正转向处）。"""
    out: List[Tuple[float, float]] = []
    for p in points:
        if out and abs(p[0] - out[-1][0]) <= EPS and abs(p[1] - out[-1][1]) <= EPS:
            continue
        while len(out) >= 2:
            a, b = out[-2], out[-1]
            if abs(_cross3(a, b, p)) <= EPS and (
                    (b[0] - a[0]) * (p[0] - b[0]) + (b[1] - a[1]) * (p[1] - b[1])) >= -EPS:
                out.pop()
            else:
                break
        out.append((p[0], p[1]))
    return out


def _rounded_path(points, radius: float = CORNER_R) -> str:
    """折线 → SVG path：拐角用 Q 贝塞尔圆角（半径收缩到相邻段长一半）。"""
    if len(points) < 3 or radius <= 0:
        d = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
        d += [f"L {p[0]:.1f} {p[1]:.1f}" for p in points[1:]]
        return " ".join(d)
    cmds = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for i in range(1, len(points) - 1):
        px, py = points[i - 1]
        cx, cy = points[i]
        nx, ny = points[i + 1]
        prev_len = math.hypot(cx - px, cy - py)
        next_len = math.hypot(nx - cx, ny - cy)
        r = min(radius, prev_len / 2, next_len / 2)
        if r < 1:
            cmds.append(f"L {cx:.1f} {cy:.1f}")
            continue
        before = (cx - (cx - px) / prev_len * r, cy - (cy - py) / prev_len * r)
        after = (cx + (nx - cx) / next_len * r, cy + (ny - cy) / next_len * r)
        cmds.append(f"L {before[0]:.1f} {before[1]:.1f}")
        cmds.append(f"Q {cx:.1f} {cy:.1f} {after[0]:.1f} {after[1]:.1f}")
    ex, ey = points[-1]
    cmds.append(f"L {ex:.1f} {ey:.1f}")
    return " ".join(cmds)


# ---------------------------------------------------------------------------
# 侧别推断与端口
# ---------------------------------------------------------------------------

def _cell_center(col: int, row: int) -> Tuple[float, float]:
    return PAD + col * CW + CW / 2, PAD + row * CH + CH / 2


def _boxes_for(nodes: List[dict]) -> Dict[str, dict]:
    boxes = {}
    for n in nodes:
        cx, cy = _cell_center(n["at"][0], n["at"][1])
        boxes[n["id"]] = {"id": n["id"], "x": cx - BOX_W / 2, "y": cy - BOX_H / 2,
                          "w": BOX_W, "h": BOX_H, "cx": cx, "cy": cy}
    return boxes


def _infer_sides(f: dict, t: dict) -> Tuple[str, str]:
    """按中心位移的主轴推断出入侧（archify defaultFromSide 的简化）。"""
    dx, dy = t["cx"] - f["cx"], t["cy"] - f["cy"]
    if dx != 0 and abs(dx) >= abs(dy):
        fs = "right" if dx > 0 else "left"
    else:
        fs = "bottom" if dy > 0 else "top"
    return fs, _OPPOSITE[fs]


def _anchor(box: dict, side: str) -> Tuple[float, float]:
    return {
        "left": (box["x"], box["cy"]),
        "right": (box["x"] + box["w"], box["cy"]),
        "top": (box["cx"], box["y"]),
        "bottom": (box["cx"], box["y"] + box["h"]),
    }[side]


def _port_has_clearance(box: dict, side: str, p: Tuple[float, float]) -> bool:
    """端点需距侧边两端留白（拐角圆角区域不放置端口）。"""
    inset = min(GUTTER, (box["h"] if side in ("left", "right") else box["w"]) / 2)
    if side in ("left", "right"):
        return box["y"] + inset - EPS <= p[1] <= box["y"] + box["h"] - inset + EPS
    return box["x"] + inset - EPS <= p[0] <= box["x"] + box["w"] - inset + EPS


def _edge_key(e: dict) -> Tuple[str, str, str]:
    return (e.get("from", ""), e.get("to", ""), e.get("label", ""))


def _spread_ports(edges: List[dict], boxes: Dict[str, dict]) -> Dict[Tuple[int, str], Tuple[float, float]]:
    """同节点同侧 ≥2 条边：沿侧边错开端点（借鉴 archify automaticPortSpread）。

    按对端中心排序让端口"指向"对端；反向边对（A→B / B→A）在两端得到
    一致的排序 → 两条平行走线。
    """
    groups: Dict[Tuple[str, str], list] = {}
    for idx, e in enumerate(edges):
        fb, tb = boxes[e["from"]], boxes[e["to"]]
        fs, ts = _infer_sides(fb, tb)
        groups.setdefault((e["from"], fs), []).append((idx, "from", tb))
        groups.setdefault((e["to"], ts), []).append((idx, "to", fb))

    ports: Dict[Tuple[int, str], Tuple[float, float]] = {}
    for (nid, side), items in groups.items():
        if len(items) < 2:
            continue
        box = boxes[nid]
        vertical = side in ("left", "right")
        axis = 1 if vertical else 0
        coord = "cy" if vertical else "cx"
        items.sort(key=lambda it: (it[2][coord], _edge_key(edges[it[0]])))
        usable = (box["h"] if vertical else box["w"]) - GUTTER * 2
        spacing = min(MAX_PORT_SPACING, usable / (len(items) - 1))
        if spacing <= EPS:
            continue
        n = len(items)
        for i, (idx, role, _counterpart) in enumerate(items):
            off = (i - (n - 1) / 2) * spacing
            p = list(_anchor(box, side))
            p[axis] += off
            if _port_has_clearance(box, side, p):
                ports[(idx, role)] = (p[0], p[1])
    return ports


def _align_facing(start, end, fs, ts, spread_from, spread_to, fbox, tbox):
    """面向侧锚点几乎对齐时拉成直线（保留 spread 端的槽位，移动未 spread 端）。"""
    h_facing = (fs, ts) in (("right", "left"), ("left", "right"))
    v_facing = (fs, ts) in (("bottom", "top"), ("top", "bottom"))
    if not (h_facing or v_facing) or (spread_from and spread_to):
        return start, end
    axis = 1 if h_facing else 0
    if abs(start[axis] - end[axis]) >= ALIGN_DELTA:
        return start, end

    def ok(s, e):
        return _port_has_clearance(fbox, fs, s) and _port_has_clearance(tbox, ts, e)

    if spread_to:  # 保住 spread 槽位，把起点拉到同一轴线
        cand = ((start[0], end[1]) if h_facing else (end[0], start[1]), end)
        if ok(*cand):
            return cand
    elif spread_from:
        cand = (start, (end[0], start[1]) if h_facing else (start[0], end[1]))
        if ok(*cand):
            return cand
    else:
        for cand in ((start, (end[0], start[1]) if h_facing else (start[0], end[1])),
                     ((start[0], end[1]) if h_facing else (end[0], start[1]), end)):
            if ok(*cand):
                return cand
    return start, end


# ---------------------------------------------------------------------------
# 正交布线
# ---------------------------------------------------------------------------

def _channels(lo: float, hi: float, step: float, boxes: Dict[str, dict], axis: int) -> List[float]:
    """Z 形布线的中间通道坐标：中点、网格分界线、盒沿 ±8、界外 ±24。

    候选按离中点远近排序，优先走居中通道。
    """
    vals = {(lo + hi) / 2, lo - 24, hi + 24}
    k = math.floor((lo - PAD) / step) + 1
    while True:
        v = PAD + k * step
        if v >= hi - 1:
            break
        if v > lo + 1:
            vals.add(v)
        k += 1
    for b in boxes.values():
        for v in ((b["x"] - 8, b["x"] + b["w"] + 8) if axis == 0
                  else (b["y"] - 8, b["y"] + b["h"] + 8)):
            if lo - 1 < v < hi + 1:
                vals.add(v)
    mid = (lo + hi) / 2
    return sorted(vals, key=lambda v: (abs(v - mid), v))


def _route_shapes(start, end, fs, ts, boxes) -> List[List[Tuple[float, float]]]:
    """给定出入侧，生成候选折线（一到两个拐角；通道逐个展开）。"""
    fh, th = fs in ("left", "right"), ts in ("left", "right")
    shapes: List[List[Tuple[float, float]]] = []
    if fh != th:
        # 单拐角：先沿 from 侧水平/垂直出去，再垂直接入 to 侧
        corner = (end[0], start[1]) if fh else (start[0], end[1])
        shapes.append([start, corner, end])
    elif fh:
        lo, hi = sorted((start[0], end[0]))
        for x in _channels(lo, hi, CW, boxes, 0):
            shapes.append([start, (x, start[1]), (x, end[1]), end])
    else:
        lo, hi = sorted((start[1], end[1]))
        for y in _channels(lo, hi, CH, boxes, 1):
            shapes.append([start, (start[0], y), (end[0], y), end])
    return shapes


def _honors_sides(points, fs, ts) -> bool:
    """首段必须沿 from 侧向外，末段必须垂直于 to 侧进入（方向契约）。"""
    def ok(a, b, side, is_source):
        sign = _SIDE_SIGN[side][0 if is_source else 1]
        if side in ("left", "right"):
            return abs(a[1] - b[1]) <= EPS and (b[0] - a[0]) * sign > EPS
        return abs(a[0] - b[0]) <= EPS and (b[1] - a[1]) * sign > EPS
    return ok(points[0], points[1], fs, True) and ok(points[-2], points[-1], ts, False)


def _validate_route(points, fbox, tbox, boxes, from_id, to_id, fs, ts):
    """规整 + 校验候选折线：侧别契约 / 最短线段 / 拐点数 / 穿盒。不合法返回 None。"""
    pts = _normalize_points(points)
    if len(pts) < 2 or not _honors_sides(pts, fs, ts):
        return None
    if len(pts) - 2 > MAX_BENDS:
        return None
    last = len(pts) - 2
    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) < MIN_SEGMENT - EPS:
            return None
        # 不相关节点盒不得穿越（含间隙）
        for nid, box in boxes.items():
            if nid in (from_id, to_id):
                continue
            if _seg_intersects_rect(a, b, box, BOX_CLEARANCE):
                return None
        # 端点盒：中间段不得重新穿回自己的盒
        if k > 0 and _seg_intersects_rect(a, b, fbox):
            return None
        if k < last and _seg_intersects_rect(a, b, tbox):
            return None
    return pts


def _route_conflicts(pts, edge, resolved) -> bool:
    """与已布的不相关边共线重叠 ≥8px 或 T 形相触 → 冲突（真正交叉不算）。"""
    for other, other_pts in resolved:
        if edge["from"] in (other["from"], other["to"]) or edge["to"] in (other["from"], other["to"]):
            continue
        for i in range(len(pts) - 1):
            for j in range(len(other_pts) - 1):
                if _collinear_overlap(pts[i], pts[i + 1], other_pts[j], other_pts[j + 1]) >= OVERLAP_MIN:
                    return True
                if _orthogonal_touch((pts[i], pts[i + 1]), (other_pts[j], other_pts[j + 1])):
                    return True
    return False


def _share_endpoint(a: dict, b: dict) -> bool:
    return a["from"] in (b["from"], b["to"]) or a["to"] in (b["from"], b["to"])


def plan_diagram(nodes: List[dict], edges: List[dict]) -> dict:
    """布线规划：返回 {routes, labels, halos, width, height}。

    routes: [(edge, points)]（按输入顺序）；labels: {idx: label dict}；
    halos: {idx: [(x1,y1,x2,y2)]} —— 后绘制的边在交叉点垫背景色粗线。
    """
    max_col = max(n["at"][0] for n in nodes)
    max_row = max(n["at"][1] for n in nodes)
    width = PAD * 2 + (max_col + 1) * CW
    height = PAD * 2 + (max_row + 1) * CH

    boxes = _boxes_for(nodes)
    ports = _spread_ports(edges, boxes)

    # 布线顺序：短边优先（借鉴 archify），距离相同按输入顺序
    order = sorted(range(len(edges)), key=lambda i: (
        abs(boxes[edges[i]["to"]]["cx"] - boxes[edges[i]["from"]]["cx"])
        + abs(boxes[edges[i]["to"]]["cy"] - boxes[edges[i]["from"]]["cy"]), i))

    routes: List[Optional[List[Tuple[float, float]]]] = [None] * len(edges)
    resolved: List[Tuple[dict, list]] = []

    for idx in order:
        e = edges[idx]
        fbox, tbox = boxes[e["from"]], boxes[e["to"]]
        inf_fs, inf_ts = _infer_sides(fbox, tbox)
        best = None  # (conflict, deviation, length, pts)
        fallback = None  # 至少几何规整的兜底（可能穿盒，lint 会报）
        for fs in [inf_fs] + [s for s in _SIDE_ORDER if s != inf_fs]:
            for ts in [inf_ts] + [s for s in _SIDE_ORDER if s != inf_ts]:
                dev = int(fs != inf_fs) + int(ts != inf_ts)
                # spread 槽位只在推断侧有效，换了侧用侧边中点
                start = ports.get((idx, "from")) if fs == inf_fs else None
                end = ports.get((idx, "to")) if ts == inf_ts else None
                start = start or _anchor(fbox, fs)
                end = end or _anchor(tbox, ts)
                start, end = _align_facing(start, end, fs, ts,
                                           fs == inf_fs and (idx, "from") in ports,
                                           ts == inf_ts and (idx, "to") in ports,
                                           fbox, tbox)
                for shape in _route_shapes(start, end, fs, ts, boxes):
                    pts = _validate_route(shape, fbox, tbox, boxes, e["from"], e["to"], fs, ts)
                    if pts is None:
                        continue
                    if fallback is None:
                        fallback = pts
                    conflict = _route_conflicts(pts, e, resolved)
                    length = sum(abs(pts[k + 1][0] - pts[k][0]) + abs(pts[k + 1][1] - pts[k][1])
                                 for k in range(len(pts) - 1))
                    score = (int(conflict), dev, length)
                    if best is None or score < best[0]:
                        best = (score, pts)
        pts = best[1] if best else (fallback or [_anchor(fbox, inf_fs), _anchor(tbox, inf_ts)])
        routes[idx] = pts
        resolved.append((e, pts))

    # 交叉 halo：两两求交（共享端点的边对跳过），后绘制的边在交点垫线
    halos: Dict[int, List[Tuple[float, float, float, float]]] = {}
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            if _share_endpoint(edges[i], edges[j]):
                continue
            for a in range(len(routes[i]) - 1):
                for b in range(len(routes[j]) - 1):
                    p = _proper_intersection(routes[i][a], routes[i][a + 1],
                                             routes[j][b], routes[j][b + 1])
                    if p is None:
                        continue
                    seg = (routes[j][b], routes[j][b + 1])
                    if abs(seg[0][0] - seg[1][0]) <= EPS:   # 竖段：上下各延 HALO_HALF
                        halo = (p[0], p[1] - HALO_HALF, p[0], p[1] + HALO_HALF)
                    else:                                    # 横段：左右各延
                        halo = (p[0] - HALO_HALF, p[1], p[0] + HALO_HALF, p[1])
                    halos.setdefault(j, []).append(halo)

    # 边标签：在最长线段上沿段滑动，避开交叉点与不相关边（水平段优先）
    labels: Dict[int, dict] = {}
    routed = list(zip(edges, routes))
    for idx, e in enumerate(edges):
        if not e.get("label"):
            continue
        pts = routes[idx]
        tw = _text_width(e["label"])
        # 与本边相交的交叉点（标签胶囊不遮交叉，交叉由 halo 表达）
        crossings = []
        for other, other_pts in routed:
            if other is e or _share_endpoint(e, other):
                continue
            for a in range(len(pts) - 1):
                for b in range(len(other_pts) - 1):
                    p = _proper_intersection(pts[a], pts[a + 1], other_pts[b], other_pts[b + 1])
                    if p:
                        crossings.append(p)

        def rect_free(rect):
            """胶囊不压交叉点、不压不相关边（与 lint 同一判定）。"""
            for px, py in crossings:
                if (rect["x"] - 4 <= px <= rect["x"] + rect["w"] + 4
                        and rect["y"] - 4 <= py <= rect["y"] + rect["h"] + 4):
                    return False
            for other, other_pts in routed:
                if other is e or _share_endpoint(e, other):
                    continue
                for b in range(len(other_pts) - 1):
                    if _seg_intersects_rect(other_pts[b], other_pts[b + 1], rect, LABEL_CLEARANCE):
                        return False
            return True

        def make_label(lx, ly, anchor):
            rx = lx - 5 if anchor == "start" else lx - tw / 2 - 5
            return {"text": e["label"], "x": lx, "y": ly, "anchor": anchor,
                    "rect": {"x": rx, "y": ly - FS_LABEL, "w": tw + 10, "h": FS_LABEL + 7}}

        # 段排序：先长后短，水平优先
        segs = []
        for a in range(len(pts) - 1):
            p, q = pts[a], pts[a + 1]
            length = abs(q[0] - p[0]) + abs(q[1] - p[1])
            is_h = abs(q[1] - p[1]) <= EPS
            segs.append((p, q, length, is_h))
        segs.sort(key=lambda s: (-s[2], not s[3]))

        chosen = None
        for p, q, _, is_h in segs:
            # 沿段滑动：中点先试，再向两侧按 12px 步进
            if is_h:
                lo, hi = sorted((p[0], q[0]))
                mid = (lo + hi) / 2
                span_lo, span_hi = lo + tw / 2 + 3, hi - tw / 2 - 3
                offsets = [0]
                k = 12
                while mid - k >= span_lo or mid + k <= span_hi:
                    offsets += [-k, k]
                    k += 12
                for off in offsets:
                    lx = (lo + hi) / 2 + off
                    if not (span_lo - 1 <= lx <= span_hi + 1):
                        continue
                    lab = make_label(lx, p[1] - 7, "middle")
                    if rect_free(lab["rect"]):
                        chosen = lab
                        break
            else:
                lo, hi = sorted((p[1], q[1]))
                mid = (lo + hi) / 2
                offsets = [0]
                k = 12
                while mid - k >= lo + 8 or mid + k <= hi - 8:
                    offsets += [-k, k]
                    k += 12
                for off in offsets:
                    ly = mid + off
                    if not (lo + 8 <= ly <= hi - 8):
                        continue
                    lab = make_label(p[0] + 8, ly + 4, "start")
                    if rect_free(lab["rect"]):
                        chosen = lab
                        break
            if chosen:
                break
        if chosen is None:
            # 兜底：最长段中点（若仍压线，lint 会报出来）
            p, q, _, is_h = segs[0]
            if is_h:
                chosen = make_label((p[0] + q[0]) / 2, p[1] - 7, "middle")
            else:
                chosen = make_label(p[0] + 8, (p[1] + q[1]) / 2 + 4, "start")
        labels[idx] = chosen

    return {"routes": list(zip(edges, routes)), "labels": labels, "halos": halos,
            "width": width, "height": height}


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def render_diagram(nodes: List[dict], edges: List[dict], caption: str = "",
                   direction: str = "lr", animated: bool = False,
                   dom_id: str = "") -> str:
    # marker id 由所属块 ID（或调用方传入的归属标识）派生：同页多图天然唯一、跨修订稳定；
    # 不用模块级计数器——那会破坏 ADR-001 确定性（同进程重复渲染输出漂移）
    marker_id = f"vr-arrow-{dom_id}" if dom_id else "vr-arrow"
    plan = plan_diagram(nodes, edges)
    W, H = plan["width"], plan["height"]

    parts = [
        f'<svg viewBox="0 0 {W} {H}" role="img" xmlns="http://www.w3.org/2000/svg" '
        f'style="max-width:{W}px;margin:0 auto;">',
        f'<defs><marker id="{marker_id}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-3)"/></marker></defs>',
    ]

    # ---- 边（线在节点下层；halo + 主线 + 流光在同一 <g>，聚焦时整组点亮/压暗） ----
    for idx, (e, pts) in enumerate(plan["routes"]):
        d = _rounded_path(pts)
        parts.append(f'<g data-edge-from="{_esc(e["from"])}" data-edge-to="{_esc(e["to"])}">')
        # crossover halo：垫背景色粗线，视觉上把交叉画成"跨线跳桥"
        for (hx1, hy1, hx2, hy2) in plan["halos"].get(idx, []):
            parts.append(
                f'<line class="vr-edge-halo" x1="{hx1:.1f}" y1="{hy1:.1f}" '
                f'x2="{hx2:.1f}" y2="{hy2:.1f}" stroke="var(--bg)" stroke-width="{HALO_WIDTH}"/>'
            )
        parts.append(
            f'<path class="vr-edge-base" d="{d}" fill="none" '
            f'stroke="var(--text-3)" stroke-width="1.5" marker-end="url(#{marker_id})"/>'
        )
        if animated:
            # 流光覆盖线：CSS dashoffset 动画沿箭头方向流动（借鉴 archify comet，
            # 纯 CSS；打印与 prefers-reduced-motion 下自动隐藏）
            parts.append(
                f'<path class="vr-edge-flow" d="{d}" fill="none" '
                f'style="animation-delay:{idx * 0.35:.2f}s"/>'
            )
        parts.append("</g>")

    # ---- 节点 ----
    boxes = _boxes_for(nodes)
    for n in nodes:
        box = boxes[n["id"]]
        color, line = KIND_STYLE.get(n.get("kind", ""), DEFAULT_STYLE)
        dash = ' stroke-dasharray="5,3"' if line == "dashed" else (
            ' stroke-dasharray="2,3"' if line == "dotted" else "")
        # 填充从描边色派生淡色调（color-mix），深浅主题下均成立（借鉴 archify）
        parts.append(
            f'<rect x="{box["x"]:.1f}" y="{box["y"]:.1f}" width="{BOX_W}" height="{BOX_H}" rx="8" '
            f'style="fill:color-mix(in srgb, {color} 10%, var(--bg))" '
            f'stroke="{color}" stroke-width="1.5"{dash} data-node-id="{_esc(n["id"])}"/>'
        )
        lines = _wrap_label(n["label"])
        total_h = 16 * len(lines)
        for i, ln in enumerate(lines):
            ty = box["cy"] - total_h / 2 + 13 + i * 16
            parts.append(
                f'<text x="{box["cx"]:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="14" '
                f'fill="var(--text-1)">{_esc(ln)}</text>'
            )

    # ---- 边标签（节点之后绘制，保证不被节点盒遮挡） ----
    for idx in sorted(plan["labels"]):
        lab = plan["labels"][idx]
        r = lab["rect"]
        # 胶囊底衬（借鉴 archify）：比文字描边晕更干净，且隔开交叉线
        parts.append(
            f'<rect x="{r["x"]:.1f}" y="{r["y"]:.1f}" width="{r["w"]:.1f}" '
            f'height="{r["h"]:.1f}" rx="7" fill="var(--bg)" stroke="var(--border)" '
            f'stroke-width="0.75"/>'
            f'<text x="{lab["x"]:.1f}" y="{lab["y"]:.1f}" text-anchor="{lab["anchor"]}" '
            f'font-size="{FS_LABEL}" font-weight="600" fill="var(--text-2)" '
            f'pointer-events="none">{_esc(lab["text"])}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# 几何 lint（diagram 2.0 第三子任务）
# ---------------------------------------------------------------------------

def lint_diagram(nodes: List[dict], edges: List[dict]) -> List[str]:
    """渲染前几何自检（确定性，与渲染共用同一套布线）：

    1. 穿盒：边线段穿过不相关节点盒（含 2px 间隙）
    2. 标签间距：标签胶囊压到不相关边的线段（含 2px 间隙）
    3. 拐点数：每边拐点 > 3
    4. 短线段：任一线段 < 8px（圆角画不出）

    真正的边交叉不算违规（渲染时垫 crossover halo）。返回诊断列表（空 = 全绿）。
    """
    try:
        plan = plan_diagram(nodes, edges)
    except Exception as exc:  # 布线本身失败（极端输入）也要能报告出来
        return [f"[diagram-geo] 布线计算失败: {exc}"]

    boxes = _boxes_for(nodes)
    issues: List[str] = []
    routes = plan["routes"]

    for idx, (e, pts) in enumerate(routes):
        where = f'边「{e["from"]}」→「{e["to"]}」'
        for n in nodes:
            if n["id"] in (e["from"], e["to"]):
                continue
            for k in range(len(pts) - 1):
                if _seg_intersects_rect(pts[k], pts[k + 1], boxes[n["id"]], BOX_CLEARANCE):
                    issues.append(f'[diagram-geo/穿盒] {where} 穿过节点「{n["id"]}」的盒子'
                                  f'（第 {k} 段）— 请调整节点网格位置或边引用')
                    break
        if len(pts) - 2 > MAX_BENDS:
            issues.append(f"[diagram-geo/拐点] {where} 有 {len(pts) - 2} 个拐点（上限 {MAX_BENDS}）"
                          "— 请拆分边或调整节点位置")
        for k in range(len(pts) - 1):
            length = abs(pts[k + 1][0] - pts[k][0]) + abs(pts[k + 1][1] - pts[k][1])
            if length < MIN_SEGMENT - EPS:
                issues.append(f"[diagram-geo/短线段] {where} 第 {k} 段仅 {length:.1f}px"
                              f"（下限 {MIN_SEGMENT}px）— 请调整节点网格位置")
                break

    for idx, lab in plan["labels"].items():
        e = routes[idx][0]
        for j, (other, other_pts) in enumerate(routes):
            if j == idx or _share_endpoint(e, other):
                continue
            for k in range(len(other_pts) - 1):
                if _seg_intersects_rect(other_pts[k], other_pts[k + 1], lab["rect"], LABEL_CLEARANCE):
                    issues.append(
                        f"[diagram-geo/标签压线] 边「{e['from']}」→「{e['to']}」的标签"
                        f"「{lab['text']}」压到边「{other['from']}」→「{other['to']}」的线段"
                        "— 请缩短标签或调整节点位置")
                    break
    return issues
