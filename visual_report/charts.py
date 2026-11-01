"""构建期 SVG 图表生成（ADR-005）：零运行时 JS，颜色走主题 token。

所有 SVG 内联进 HTML，因此 fill/stroke 直接引用 var(--chart-N) 等主题变量，
换主题时图表自动跟随。
"""

import html
import math
from typing import List, Optional, Sequence

CHART_COLORS = [f"var(--chart-{i})" for i in range(1, 7)]
_AXIS_COLOR = "var(--border)"
_LABEL_COLOR = "var(--text-2)"
_VALUE_COLOR = "var(--text-1)"
_GRID_COLOR = "var(--border)"

W, H = 720, 360  # viewBox 尺寸
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 24, 48


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _fmt(v: float) -> str:
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _nice_max(values: Sequence[float]) -> float:
    vmax = max(values) if values else 1
    if vmax <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(vmax))
    for m in (1, 2, 2.5, 5, 10):
        if vmax <= m * magnitude:
            return m * magnitude
    return 10 * magnitude


def bar_chart(labels: List[str], values: List[Optional[float]], series=None,
              unit: str = "") -> str:
    """柱状图。支持单序列（values）或多序列（series: [{name, values}]）。"""
    if series:
        names = [s["name"] for s in series]
        data = [s["values"] for s in series]
    else:
        names, data = None, [values]

    n = len(labels)
    k = len(data)
    all_vals = [v for row in data for v in row if v is not None]
    vmax = _nice_max(all_vals)

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    group_w = plot_w / n
    bar_w = min(48, (group_w * 0.72) / k)

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" xmlns="http://www.w3.org/2000/svg">']

    # 网格线 + Y 轴刻度（4 段）
    for i in range(5):
        y = PAD_T + plot_h - plot_h * i / 4
        val = vmax * i / 4
        parts.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="{_GRID_COLOR}" stroke-width="1"/>'
            f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="{_LABEL_COLOR}">{_fmt(val)}</text>'
        )

    # 柱体
    for gi, label in enumerate(labels):
        group_cx = PAD_L + group_w * (gi + 0.5)
        for si, row in enumerate(data):
            v = row[gi]
            if v is None:
                continue
            h_ = plot_h * (v / vmax)
            x = group_cx - (bar_w * k) / 2 + si * bar_w
            y = PAD_T + plot_h - h_
            color = CHART_COLORS[si % len(CHART_COLORS)]
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 2:.1f}" height="{max(h_, 1):.1f}" '
                f'rx="3" fill="{color}"/>'
            )
        # 单序列时在柱顶标数值
        if k == 1 and data[0][gi] is not None:
            v = data[0][gi]
            y = PAD_T + plot_h - plot_h * (v / vmax)
            parts.append(
                f'<text x="{group_cx:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                f'font-size="12" font-weight="600" fill="{_VALUE_COLOR}">{_fmt(v)}{unit}</text>'
            )
        # X 轴标签
        parts.append(
            f'<text x="{group_cx:.1f}" y="{H - PAD_B + 20}" text-anchor="middle" '
            f'font-size="12" fill="{_LABEL_COLOR}">{_esc(label)}</text>'
        )

    # 多序列图例
    if names:
        lx = PAD_L
        for si, name in enumerate(names):
            color = CHART_COLORS[si % len(CHART_COLORS)]
            parts.append(
                f'<rect x="{lx}" y="4" width="10" height="10" rx="2" fill="{color}"/>'
                f'<text x="{lx + 14}" y="13" font-size="12" fill="{_LABEL_COLOR}">{_esc(name)}</text>'
            )
            lx += 28 + 12 * len(str(name)) + 8

    parts.append("</svg>")
    return "".join(parts)


def line_chart(labels: List[str], values: List[Optional[float]], series=None,
               unit: str = "") -> str:
    """折线图。null 值断线呈现（ADR-009：缺值不得编造）。"""
    if series:
        names = [s["name"] for s in series]
        data = [s["values"] for s in series]
    else:
        names, data = None, [values]

    n = max(len(labels), max(len(r) for r in data))
    all_vals = [v for row in data for v in row if v is not None]
    vmax = _nice_max(all_vals)
    vmin = 0

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    step = plot_w / max(n - 1, 1)

    def px(i):
        return PAD_L + step * i

    def py(v):
        return PAD_T + plot_h - plot_h * ((v - vmin) / (vmax - vmin or 1))

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" xmlns="http://www.w3.org/2000/svg">']

    for i in range(5):
        y = PAD_T + plot_h - plot_h * i / 4
        val = vmin + (vmax - vmin) * i / 4
        parts.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="{_GRID_COLOR}" stroke-width="1"/>'
            f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="{_LABEL_COLOR}">{_fmt(val)}</text>'
        )

    for si, row in enumerate(data):
        color = CHART_COLORS[si % len(CHART_COLORS)]
        # 按 null 切段，每段独立 polyline（断线语义）
        seg, segs = [], []
        for i, v in enumerate(row):
            if v is None:
                if seg:
                    segs.append(seg)
                seg = []
            else:
                seg.append((i, v))
        if seg:
            segs.append(seg)

        for seg_pts in segs:
            pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in seg_pts)
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
            for i, v in seg_pts:
                parts.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="3.5" fill="{color}"/>')

    # X 轴标签（数量多时隔行显示）
    every = max(1, math.ceil(n / 12))
    for i, label in enumerate(labels):
        if i % every != 0 and i != n - 1:
            continue
        parts.append(
            f'<text x="{px(i):.1f}" y="{H - PAD_B + 20}" text-anchor="middle" '
            f'font-size="12" fill="{_LABEL_COLOR}">{_esc(label)}</text>'
        )

    if names:
        lx = PAD_L
        for si, name in enumerate(names):
            color = CHART_COLORS[si % len(CHART_COLORS)]
            parts.append(
                f'<line x1="{lx}" y1="9" x2="{lx + 16}" y2="9" stroke="{color}" stroke-width="3"/>'
                f'<text x="{lx + 20}" y="13" font-size="12" fill="{_LABEL_COLOR}">{_esc(name)}</text>'
            )
            lx += 40 + 12 * len(str(name)) + 8

    parts.append("</svg>")
    return "".join(parts)


def donut_chart(labels: List[str], values: List[Optional[float]], unit: str = "") -> str:
    """环形图。null / 0 值不渲染扇区。"""
    pairs = [(l, v) for l, v in zip(labels, values) if v is not None and v > 0]
    total = sum(v for _, v in pairs) or 1

    size = 260
    cx = cy = size / 2
    r = 92
    stroke = 34
    circumference = 2 * math.pi * r

    parts = [
        f'<svg viewBox="0 0 {size} {size}" role="img" xmlns="http://www.w3.org/2000/svg" '
        f'style="max-width:{size}px;margin:0 auto;">'
    ]

    offset = 0.0
    for i, (label, v) in enumerate(pairs):
        frac = v / total
        dash = frac * circumference
        color = CHART_COLORS[i % len(CHART_COLORS)]
        # stroke-dasharray = [弧长, 空隙]，rotate 从 12 点方向起
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash

    parts.append(
        f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-size="22" font-weight="700" '
        f'fill="var(--text-1)">{_fmt(total)}</text>'
        f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" font-size="12" fill="var(--text-3)">总计{unit}</text>'
        f"</svg>"
    )

    # 图例
    legend = "".join(
        f'<li><span style="background:{CHART_COLORS[i % len(CHART_COLORS)]}"></span>'
        f"{_esc(label)} · {_fmt(v)} ({v / total * 100:.0f}%)</li>"
        for i, (label, v) in enumerate(pairs)
    )
    legend_html = (
        f'<ul class="vr-chart-legend">{legend}</ul>'
    )
    return "".join(parts) + legend_html
