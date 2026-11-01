"""幻灯片渲染器（Phase 4）：slide-plan.json → 单文件离线 HTML deck。

设计（ADR-005/006 延续）：
- 1280×720 固定画布 + JS transform 缩放自适应（借鉴 vislide）
- 交互运行时为 ~150 行原生 JS（翻页/全屏/总览/进度/备注），不引入外部框架
- 复用报告模式的块渲染器与主题 token——两模式共享视觉系统、独立布局体系（ADR-002）
"""

import html
from pathlib import Path
from typing import Optional

from . import __version__
from .blocks import render_block
from .render import _load_css
from .validate import validate_report_or_raise

RUNTIME_JS = """(function(){
  var deck = document.querySelector('.vr-deck');
  var slides = [].slice.call(document.querySelectorAll('.vr-slide'));
  if (!deck || !slides.length) return;
  var cur = 0, overview = false;

  function go(n, push){
    cur = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function(s, i){ s.classList.toggle('vr-active', i === cur); });
    document.querySelector('.vr-progress > span').style.width = ((cur + 1) / slides.length * 100) + '%';
    document.querySelector('.vr-counter').textContent = (cur + 1) + ' / ' + slides.length;
    if (push !== false) history.replaceState(null, '', '#/' + cur);
  }

  function fit(){
    var s = Math.min(innerWidth / 1280, innerHeight / 720);
    deck.style.transform = 'scale(' + s + ')';
    if (overview) layoutOverview(true);
  }

  function layoutOverview(on){
    overview = on;
    deck.classList.toggle('vr-overview', on);
    slides.forEach(function(s, i){
      if (!on) { s.style.transform = ''; s.style.opacity = ''; return; }
      var col = i % 4, row = Math.floor(i / 4);
      var sc = 0.22;
      s.style.transform = 'translate(' + (col * 300 + 40) + 'px,' + (row * 190 + 30) + 'px) scale(' + sc + ')';
      s.style.opacity = (i === cur) ? '1' : '0.55';
      s.classList.toggle('vr-active-in-overview', i === cur);
    });
  }

  function pickFromOverview(i){ layoutOverview(false); go(i); }

  addEventListener('resize', fit);
  addEventListener('keydown', function(e){
    if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { e.preventDefault(); if(!overview) go(cur + 1); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); if(!overview) go(cur - 1); }
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(slides.length - 1);
    else if (e.key === 'f' || e.key === 'F') { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen(); }
    else if (e.key === 'o' || e.key === 'O') { layoutOverview(!overview); }
    else if (e.key === 'n' || e.key === 'N') { var nb = document.querySelector('.vr-notes'); if (nb) nb.classList.toggle('vr-notes-open'); }
  });
  deck.addEventListener('click', function(e){
    var s = e.target.closest('.vr-slide');
    if (overview && s) { pickFromOverview(slides.indexOf(s)); return; }
    if (e.target.closest('a')) return;
    if (!overview) go(cur + 1);
  });

  // 深链 #/N
  var m = location.hash.match(/^#\\/(\d+)/);
  fit(); go(m ? parseInt(m[1], 10) : 0, false);
})();"""


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _slide_inner(sl: dict, base_dir: Optional[Path], meta: dict) -> str:
    layout = sl["layout"]
    blocks = "".join(render_block(b, base_dir) for b in sl.get("blocks", []))
    notes = (
        f'<div class="vr-note-text" data-note="{_esc(sl["id"])}">{_esc(sl["notes"])}</div>'
        if sl.get("notes") else ""
    )

    if layout == "title":
        parts = []
        if meta.get("author"):
            parts.append(f'<span>{_esc(meta["author"])}</span>')
        if meta.get("date"):
            parts.append(f'<span>{_esc(meta["date"])}</span>')
        return (
            f'<div class="vr-slide-title"><h1>{_esc(sl["title"])}</h1>'
            + (f'<p class="vr-slide-sub">{_esc(sl["subtitle"])}</p>' if sl.get("subtitle") else "")
            + f'<div class="vr-slide-meta">{"".join(parts)}</div></div>'
            + (f'<div class="vr-slide-blocks vr-slide-blocks--center">{blocks}</div>' if blocks else "")
            + notes
        )

    if layout == "section":
        return (
            f'<div class="vr-slide-divider">'
            + (f'<span class="vr-section-kicker">{_esc(sl["kicker"])}</span>' if sl.get("kicker") else "")
            + f'<h1>{_esc(sl["title"])}</h1>'
            + (f'<p class="vr-slide-sub">{_esc(sl["subtitle"])}</p>' if sl.get("subtitle") else "")
            + "</div>" + notes
        )

    if layout == "statement":
        return f'<div class="vr-slide-statement"><h1>{_esc(sl["title"])}</h1>' \
               + (f'<p class="vr-slide-sub">{_esc(sl["subtitle"])}</p>' if sl.get("subtitle") else "") \
               + "</div>" + notes

    head = (
        (f'<span class="vr-section-kicker">{_esc(sl["kicker"])}</span>' if sl.get("kicker") else "")
        + f'<h2 class="vr-slide-h2">{_esc(sl["title"])}</h2>'
        + (f'<p class="vr-slide-sub">{_esc(sl["subtitle"])}</p>' if sl.get("subtitle") else "")
    )
    return f'<header class="vr-slide-head">{head}</header>' \
           + (f'<div class="vr-slide-blocks">{blocks}</div>' if blocks else "") + notes


def render_deck(plan: dict, base_dir: Optional[Path] = None) -> str:
    """校验 + 渲染幻灯片 deck。校验失败抛 ValidationError（不产出文件）。"""
    validate_report_or_raise(plan)  # 内部按 slides 键路由到 validate_slide

    meta = plan["meta"]
    theme = meta.get("theme", "minimal")

    slides_html = "".join(
        f'<section class="vr-slide vr-slide--{s["layout"]}" id="{_esc(s["id"])}">'
        + _slide_inner(s, base_dir, meta) + "</section>"
        for s in plan["slides"]
    )
    notes = "".join(
        f'<p data-note="{_esc(s["id"])}"><b>{_esc(s["title"])}</b><br>{_esc(s.get("notes", ""))}</p>'
        for s in plan["slides"] if s.get("notes")
    )
    footer_text = meta.get("footer") or meta.get("title", "")

    return f"""<!DOCTYPE html>
<html lang="{_esc(meta.get('lang', 'zh-CN'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="visual-report {_esc(__version__)}">
<title>{_esc(meta['title'])}</title>
<style>
{_load_css(theme)}
</style>
</head>
<body class="vr-deck-body">
<div class="vr-stage">
<div class="vr-deck">
{slides_html}
</div>
</div>
<div class="vr-progress"><span></span></div>
<div class="vr-counter">1 / {len(plan['slides'])}</div>
<div class="vr-hint">← → 翻页 · F 全屏 · O 总览 · N 备注</div>
<div class="vr-notes"><h3>演讲者备注</h3>{notes}</div>
<footer class="vr-deck-footer">{_esc(footer_text)}</footer>
<script>
{RUNTIME_JS}
</script>
</body>
</html>
"""
