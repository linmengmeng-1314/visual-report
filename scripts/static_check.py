#!/usr/bin/env python3
"""第二层质检（ADR-003）：对渲染产物 HTML 做静态检查，无需浏览器。

检查项：
  1. 外部资源（http/https 的 link/img/script/src）→ FAILED（离线约束）
  2. 未内嵌的 <link>/<script src> → FAILED
  3. 空 src / href 的资源引用 → FAILED
  4. 内部锚点有效性（#id 均存在）→ FAILED
  5. 重复 DOM id → FAILED
  6. 空内容区域（section 内无任何文本）→ WARNING
  7. 弱标题检查（agenda/overview/thank you 等，E7）→ WARNING
  8. 体积门禁（ADR-006：默认目标 2MB / 硬上限 5MB）→ 超目标 WARNING，超上限 FAILED

用法：
    python scripts/inspect.py output/visual-report.html [--json qa/static-check.json]
退出码：0 = PASS，1 = WARNING，2 = FAILED。
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

SIZE_TARGET = 2 * 1024 * 1024   # 2MB 目标
SIZE_LIMIT = 5 * 1024 * 1024    # 5MB 硬上限

WEAK_TITLES = {"agenda", "overview", "summary", "thank you", "谢谢", "目录", "概述", "总结", "appendix"}


class _Inspector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors: list = []
        self.warnings: list = []
        self.ids: dict = {}          # id -> 出现次数
        self.anchors: set = set()    # #href 目标
        self.ext_resources: list = []
        self.uninlined: list = []
        self.empty_src: list = []
        self.sections: list = []     # (tag, attrs snapshot)
        self._current_section = None
        self._section_has_text = False
        self._section_title = ""
        self._in_heading = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids[a["id"]] = self.ids.get(a["id"], 0) + 1
        if tag == "a" and a.get("href", "").startswith("#") and len(a.get("href", "")) > 1:
            self.anchors.add(a["href"][1:])

        if tag in ("link", "script", "img", "source", "iframe"):
            for attr in ("href", "src"):
                url = a.get(attr)
                if url is None:
                    continue
                if not url.strip():
                    self.empty_src.append(f"<{tag} {attr}=\"\">")
                elif url.startswith(("http://", "https://", "//")):
                    self.ext_resources.append(f"<{tag} {attr}={url[:80]}>")
                elif url.startswith(("data:", "#")):
                    pass
                elif tag in ("link", "script") and not url.startswith("#"):
                    # 未内嵌的外部文件引用（file:// 或相对路径都不允许）
                    self.uninlined.append(f"<{tag} {attr}={url[:80]}>")

        if tag == "section":
            self._current_section = a.get("id", "?")
            self._section_has_text = False
        if tag in ("h1", "h2") and self._current_section:
            self._in_heading = True

    def handle_data(self, data):
        if data.strip():
            if self._current_section:
                self._section_has_text = True
            if self._in_heading:
                t = data.strip().lower()
                if t in WEAK_TITLES:
                    self.warnings.append(
                        f"[weak-title] section {self._current_section}: 弱标题「{data.strip()}」，"
                        "建议改为陈述观点的 action title"
                    )

    def handle_endtag(self, tag):
        if tag == "section" and self._current_section:
            if not self._section_has_text:
                self.warnings.append(f"[empty] section {self._current_section}: 无任何文本内容")
            self._current_section = None
        if tag in ("h1", "h2"):
            self._in_heading = False


def inspect_html(path: Path) -> dict:
    html_text = path.read_text(encoding="utf-8")
    size = path.stat().st_size

    p = _Inspector()
    p.feed(html_text)

    for r in p.ext_resources:
        p.errors.append(f"[offline] 外部资源引用: {r}")
    for r in p.uninlined:
        p.errors.append(f"[inline] CSS/JS 未内嵌: {r}")
    for r in p.empty_src:
        p.errors.append(f"[empty-src] 空 src/href: {r}")

    for anchor in sorted(p.anchors):
        if anchor not in p.ids:
            p.errors.append(f"[anchor] 锚点 #{anchor} 无对应元素")
    for dom_id, count in p.ids.items():
        if count > 1:
            p.errors.append(f"[dup-id] id「{dom_id}」出现 {count} 次")

    size_state = "ok"
    if size > SIZE_LIMIT:
        p.errors.append(
            f"[size] 单文件 {size / 1024 / 1024:.2f}MB 超过硬上限 5MB（ADR-006）"
        )
        size_state = "failed"
    elif size > SIZE_TARGET:
        p.warnings.append(
            f"[size] 单文件 {size / 1024 / 1024:.2f}MB 超过目标 2MB（硬上限 5MB）"
        )
        size_state = "warning"

    if p.errors:
        status = "FAILED"
    elif p.warnings:
        status = "WARNING"
    else:
        status = "PASS"

    return {
        "file": str(path),
        "status": status,
        "sizeBytes": size,
        "sizeState": size_state,
        "errors": p.errors,
        "warnings": p.warnings,
        "sections": len(p.ids) and sum(1 for i in p.ids if not i.startswith("vr-")),
        "checkedAtVersion": "static-check/0.1",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染产物静态检查（第二层质检）")
    parser.add_argument("html", help="渲染产物 HTML 路径")
    parser.add_argument("--json", help="检查结果 JSON 输出路径")
    args = parser.parse_args()

    result = inspect_html(Path(args.html))

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    for e in result["errors"]:
        print(f"  ✗ {e}")
    for w in result["warnings"]:
        print(f"  ⚠ {w}")
    print(f"{result['status']} — {result['file']} ({result['sizeBytes'] / 1024:.0f} KB, "
          f"{len(result['errors'])} errors / {len(result['warnings'])} warnings)")
    return {"PASS": 0, "WARNING": 1, "FAILED": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
