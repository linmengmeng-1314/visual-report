"""块渲染器：block dict → HTML。所有纯文本字段经 html 转义，Markdown 字段经 md_to_html。"""

import base64
import html
import mimetypes
from pathlib import Path
from typing import Optional

from . import charts
from .diagram import render_diagram
from .md import md_to_html


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _embed_image(src: str, base_dir: Optional[Path]) -> str:
    """本地图片 → data: URI（ADR：禁止外部资源）。data: URI 原样返回。"""
    if src.startswith("data:"):
        return src
    path = (base_dir / src) if base_dir else Path(src)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在: {path}")
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def render_block(blk: dict, base_dir: Optional[Path] = None) -> str:
    btype = blk["type"]
    bid = f' id="{_esc(blk["id"])}"' if blk.get("id") else ""
    fn = _BLOCK_RENDERERS.get(btype)
    if fn is None:
        raise ValueError(f"未知块类型: {btype}")
    inner = fn(blk, base_dir)
    return f'<div class="vr-block vr-block--{btype}"{bid}>{inner}</div>'


def _r_text(blk, _):
    return f'<div class="vr-prose">{md_to_html(blk["content"])}</div>'


def _r_heading(blk, _):
    level = blk.get("level", 2)
    return f"<h{level}>{_esc(blk['content'])}</h{level}>"


def _r_list(blk, _):
    tag = "ol" if blk.get("ordered") else "ul"
    items = "".join(f"<li>{md_to_html(i)}</li>" for i in blk["items"])
    return f"<{tag}>{items}</{tag}>"


def _r_quote(blk, _):
    cite = f'<cite>{_esc(blk["cite"])}</cite>' if blk.get("cite") else ""
    return f'<blockquote class="vr-quote">{md_to_html(blk["content"])}{cite}</blockquote>'


def _r_callout(blk, _):
    tag = _esc(blk.get("tag", "要点"))
    return (
        f'<div class="vr-callout"><span class="vr-callout-tag">{tag}</span>'
        f'<div class="vr-prose">{md_to_html(blk["content"])}</div></div>'
    )


def _r_code(blk, _):
    code = _esc(blk["content"].rstrip("\n"))
    lang = _esc(blk.get("language", ""))
    caption = (
        f'<figcaption class="vr-figure-caption">{_esc(blk["caption"])}</figcaption>'
        if blk.get("caption") else ""
    )
    return f"<figure><pre><code class=\"language-{lang}\">{code}</code></pre>{caption}</figure>"


def _r_image(blk, base_dir):
    src = _embed_image(blk["src"], base_dir)
    alt = _esc(blk.get("alt", ""))
    caption = (
        f'<figcaption class="vr-figure-caption">{_esc(blk["caption"])}</figcaption>'
        if blk.get("caption") else ""
    )
    style = f' style="max-width:{_esc(blk.get("maxWidth", "100%"))}"' if blk.get("maxWidth") else ""
    return f'<figure class="vr-figure"><img src="{src}" alt="{alt}"{style}/>{caption}</figure>'


def _r_kpi(blk, _):
    items = []
    for it in blk["items"]:
        delta = ""
        if it.get("delta"):
            trend = it.get("trend", "flat")
            # 颜色表达"好坏"，箭头表达"方向"，二者解耦（good 显式指定时优先生效）
            improved = it.get("good", trend == "up")
            cls = "vr-kpi-delta--up" if improved else "vr-kpi-delta--down"
            arrow = {"up": "▲", "down": "▼", "flat": ""}.get(trend, "")
            delta = f'<div class="vr-kpi-delta {cls}">{arrow} {_esc(it["delta"])}</div>'
        items.append(
            f'<div class="vr-kpi"><div class="vr-kpi-value">{_esc(it["value"])}</div>'
            f'<div class="vr-kpi-label">{_esc(it["label"])}</div>{delta}</div>'
        )
    return f'<div class="vr-kpis">{"".join(items)}</div>'


def _r_chart(blk, _):
    data = blk["data"]
    ctype = blk["chartType"]
    unit = blk.get("unit", "")
    if ctype == "bar":
        svg = charts.bar_chart(data["labels"], data.get("values", []), data.get("series"), unit)
    elif ctype == "line":
        svg = charts.line_chart(data["labels"], data.get("values", []), data.get("series"), unit)
    elif ctype == "donut":
        svg = charts.donut_chart(data["labels"], data.get("values", []), unit)
    else:
        raise ValueError(f"未知图表类型: {ctype}")
    caption = (
        f'<figcaption class="vr-figure-caption">{_esc(blk["caption"])}</figcaption>'
        if blk.get("caption") else ""
    )
    note = (
        f'<figcaption class="vr-figure-caption" style="margin-top:0;font-style:italic">'
        f"数据说明：{_esc(blk['dataNote'])}</figcaption>"
        if blk.get("dataNote") else ""
    )
    return f'<figure class="vr-chart">{svg}{caption}{note}</figure>'


def _r_table(blk, _):
    thead = "".join(f"<th>{_esc(c)}</th>" for c in blk["columns"])
    rows = "".join(
        "<tr>" + "".join(f"<td>{_esc(v if v is not None else '—')}</td>" for v in row) + "</tr>"
        for row in blk["rows"]
    )
    caption = (
        f'<figcaption class="vr-figure-caption">{_esc(blk["caption"])}</figcaption>'
        if blk.get("caption") else ""
    )
    return (
        f'<figure><div style="overflow-x:auto;"><table><thead><tr>{thead}</tr></thead>'
        f"<tbody>{rows}</tbody></table></div>{caption}</figure>"
    )


def _r_timeline(blk, _):
    items = "".join(
        f'<li><div class="vr-tl-time">{_esc(it["time"])}</div>'
        f'<div class="vr-tl-title">{_esc(it["title"])}</div>'
        + (f'<p class="vr-tl-desc">{_esc(it["desc"])}</p>' if it.get("desc") else "")
        + "</li>"
        for it in blk["items"]
    )
    return f'<ul class="vr-timeline">{items}</ul>'


def _r_cards(blk, _):
    cards = []
    for it in blk["items"]:
        icon = f'<span class="vr-card-icon">{_esc(it["icon"])}</span>' if it.get("icon") else ""
        cards.append(
            f'<div class="vr-card">{icon}<h4>{_esc(it["title"])}</h4>'
            f'<div class="vr-prose">{md_to_html(it["content"])}</div></div>'
        )
    return f'<div class="vr-cards">{"".join(cards)}</div>'


def _r_columns(blk, _):
    cols = "".join(f'<div class="vr-prose">{md_to_html(c)}</div>' for c in blk["cols"])
    return f'<div class="vr-cols">{cols}</div>'


def _r_diagram(blk, _):
    svg = render_diagram(
        blk["nodes"], blk.get("edges", []), blk.get("caption", ""),
        blk.get("direction", "lr"),
    )
    caption = (
        f'<figcaption class="vr-figure-caption">{_esc(blk["caption"])}</figcaption>'
        if blk.get("caption") else ""
    )
    return f'<figure class="vr-chart">{svg}{caption}</figure>'


_BLOCK_RENDERERS = {
    "text": _r_text,
    "heading": _r_heading,
    "list": _r_list,
    "quote": _r_quote,
    "callout": _r_callout,
    "code": _r_code,
    "image": _r_image,
    "kpi": _r_kpi,
    "chart": _r_chart,
    "diagram": _r_diagram,
    "table": _r_table,
    "timeline": _r_timeline,
    "cards": _r_cards,
    "columns": _r_columns,
}
