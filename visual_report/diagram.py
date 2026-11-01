"""构建期 SVG 流程/架构图（ADR-005，参考 ve-flow 的网格坐标声明式设计）。

节点用 "at": [col, row] 网格坐标声明，边用节点 ID 引用；
Renderer 负责布局、连线和箭头，AI 不需要算坐标。
"""

import html
from typing import Dict, List, Optional

CW, CH = 196, 96          # 网格单元尺寸（间隙需容纳边标签）
BOX_W, BOX_H = 136, 62    # 节点盒尺寸
PAD = 24

# kind → 视觉样式（描边色 + 线型），未声明的 kind 用默认样式
KIND_STYLE = {
    "client":   ("var(--chart-6)", "solid"),
    "service":  ("var(--chart-1)", "solid"),
    "storage":  ("var(--chart-3)", "dashed"),
    "queue":    ("var(--chart-4)", "dashed"),
    "external": ("var(--text-2)",  "dotted"),
}
DEFAULT_STYLE = ("var(--border)", "solid")


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


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


def _cell_center(col: int, row: int) -> tuple:
    return PAD + col * CW + CW / 2, PAD + row * CH + CH / 2


def _box_at(cx: float, cy: float) -> tuple:
    return cx - BOX_W / 2, cy - BOX_H / 2, BOX_W, BOX_H


def _trim_to_box(x1: float, y1: float, x2: float, y2: float) -> tuple:
    """把中心到中心的线段裁剪到节点盒边缘（水平/垂直连线场景的近似）。"""
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1:  # 垂直
        dy_trim = (BOX_H / 2 + 2) * (1 if dy > 0 else -1)
        return x1, y1 + dy_trim, x2, y2 - dy_trim
    if abs(dy) < 1:  # 水平
        dx_trim = (BOX_W / 2 + 2) * (1 if dx > 0 else -1)
        return x1 + dx_trim, y1, x2 - dx_trim, y2
    # 斜向：同时裁两端（画直线，简单可靠）
    import math
    L = math.hypot(dx, dy)
    t = (BOX_W / 2 + 4) / L if abs(dx) >= abs(dy) else (BOX_H / 2 + 4) / L
    return x1 + dx * t, y1 + dy * t, x2 - dx * t, y2 - dy * t


def render_diagram(nodes: List[dict], edges: List[dict], caption: str = "",
                   direction: str = "lr") -> str:
    max_col = max(n["at"][0] for n in nodes)
    max_row = max(n["at"][1] for n in nodes)
    W = PAD * 2 + (max_col + 1) * CW
    H = PAD * 2 + (max_row + 1) * CH

    centers: Dict[str, tuple] = {}
    for n in nodes:
        centers[n["id"]] = _cell_center(n["at"][0], n["at"][1])

    parts = [
        f'<svg viewBox="0 0 {W} {H}" role="img" xmlns="http://www.w3.org/2000/svg" '
        f'style="max-width:{W}px;margin:0 auto;">',
        f'<defs><marker id="vr-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-3)"/></marker></defs>',
    ]

    # ---- 边（线在节点下层） ----
    labels_svg = []  # 标签统一在节点之后绘制，保证不被节点盒遮挡
    for e in edges:
        x1, y1 = centers[e["from"]]
        x2, y2 = centers[e["to"]]
        sx, sy, ex, ey = _trim_to_box(x1, y1, x2, y2)
        parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="var(--text-3)" stroke-width="1.5" marker-end="url(#vr-arrow)"/>'
        )
        if e.get("label"):
            mx, my = (sx + ex) / 2, (sy + ey) / 2
            if abs(ex - sx) < 1:      # 垂直边：标签放线右侧
                lx, ly, anchor = mx + 7, my + 3, "start"
            elif abs(ey - sy) < 1:    # 水平边：标签在线上方
                lx, ly, anchor = mx, my - 6, "middle"
            else:                     # 斜边：中点上方
                lx, ly, anchor = mx, my - 6, "middle"
            # 描边晕底避免与连线/邻线串扰
            labels_svg.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12" font-weight="600" '
                f'fill="var(--text-2)" stroke="var(--bg)" stroke-width="3" '
                f'paint-order="stroke">{_esc(e["label"])}</text>'
            )

    # ---- 节点 ----
    for n in nodes:
        cx, cy = centers[n["id"]]
        bx, by, bw, bh = _box_at(cx, cy)
        color, line = KIND_STYLE.get(n.get("kind", ""), DEFAULT_STYLE)
        dash = ' stroke-dasharray="5,3"' if line == "dashed" else (
            ' stroke-dasharray="2,3"' if line == "dotted" else "")
        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw}" height="{bh}" rx="8" '
            f'fill="var(--surface)" stroke="{color}" stroke-width="1.5"{dash}/>'
        )
        lines = _wrap_label(n["label"])
        total_h = 16 * len(lines)
        for i, ln in enumerate(lines):
            ty = cy - total_h / 2 + 13 + i * 16
            parts.append(
                f'<text x="{cx:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="14" '
                f'fill="var(--text-1)">{_esc(ln)}</text>'
            )

    # 标签绘制在节点之后（SVG 内后绘制的元素在上层），再闭合标签
    parts.extend(labels_svg)
    parts.append("</svg>")
    return "".join(parts)
