"""Markdown → HTML（ADR-008：内容块统一由 Renderer 转换，AI 不写 HTML）。"""

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"typographer": True, "linkify": False}).enable("table")


def md_to_html(text: str) -> str:
    """把 Markdown 字符串渲染为 HTML 片段。"""
    return _md.render(text or "")
