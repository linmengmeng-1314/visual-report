#!/usr/bin/env python3
"""第三层质检（ADR-003）：浏览器渲染检查 + 截图。

可选依赖：安装 playwright（pip install playwright）后自动启用；
未安装时明确提示并跳过（退出码 3 = SKIPPED），不阻断 HTML 交付。
浏览器回退链：系统 Chrome → 系统 Edge → Playwright 自带 Chromium，无需下载
（Windows 上 Chrome 常因管理员终端/常驻实例的 DevTools 管道问题不可用，Edge 无头实测可用、命中率高）。

检查项：
  1. 视口横向溢出（桌面 1280 / 移动 375 两档）
  2. 破损图片（naturalWidth == 0）
  3. section 级内容溢出（scrollWidth > clientWidth，表格/图表撑破容器）
  4. 全页 + 逐 section 截图存证

用法：
    python scripts/visual_check.py output/visual-report.html [--json output/qa/visual-check.json]
退出码：0 PASS / 1 WARNING / 2 FAILED / 3 SKIPPED。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

# 中文 Windows 控制台重定向输出时按 GBK 编码，✓/✗ 等符号会触发 UnicodeEncodeError——统一切 UTF-8（Mac/Linux 已是 UTF-8，此段无操作）
for _s in (sys.stdout, sys.stderr):
    _rc = getattr(_s, "reconfigure", None)
    if _rc and getattr(_s, "encoding", "").lower().replace("-", "") != "utf8":
        _rc(encoding="utf-8")

VIEWPORTS = [("desktop", 1280, 900), ("mobile", 375, 812)]


def _url(path: Path) -> str:
    return "file://" + urllib.parse.quote(str(path.resolve()))


def _find_system_browser():
    """系统浏览器可执行文件：Edge 优先（Windows 上 Chrome 常因管理员终端/常驻实例不可用）。"""
    candidates = []
    # Windows 环境变量查找大小写不敏感；x86 路径的真实变量名是 ProgramFiles(x86)
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates += [
                Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
            ]
    for c in candidates:
        if c.is_file():
            return str(c)
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def degraded_screenshots(html_path: Path, shot_dir: Path):
    """无 playwright 时的降级目检（B2）：系统浏览器无头整页截图。

    只覆盖「人工目检」，溢出/裂图的自动判定仍需 playwright（JS 求值）。
    无 JS 可用、量不到页面高度，取保守高窗（dogfood 实测 1280×11000 可整页）。
    注意：截图文件落盘有秒级延迟——轮询等待而非查一次。
    返回截图路径；浏览器不可用或超时返回 None。
    """
    browser = _find_system_browser()
    if not browser:
        return None
    shot_dir.mkdir(parents=True, exist_ok=True)
    out = shot_dir / "degraded-desktop.png"
    subprocess.run(
        [browser, "--headless", f"--screenshot={out}", "--window-size=1280,11000", _url(html_path)],
        capture_output=True, timeout=60,
    )
    for _ in range(30):  # 落盘延迟：轮询至多 ~15s
        if out.exists() and out.stat().st_size > 0:
            return out
        time.sleep(0.5)
    return None


def run_checks(html_path: Path, shot_dir: Path):
    from playwright.sync_api import sync_playwright

    issues, warnings = [], []
    shot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # 回退链：系统 Chrome → 系统 Edge → Playwright 自带 Chromium
        browser = None
        for launch_kwargs in ({"channel": "chrome"}, {"channel": "msedge"}, {}):
            try:
                browser = p.chromium.launch(**launch_kwargs)
                break
            except Exception:
                continue
        if browser is None:
            raise RuntimeError("Chrome / Edge / Chromium 均启动失败，请检查浏览器安装")

        for vname, width, height in VIEWPORTS:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(_url(html_path))
            page.wait_for_load_state("networkidle")

            # 1. 页面横向溢出
            overflow = page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            if overflow > 2:
                issues.append(
                    f"[overflow:{vname}] 页面横向溢出 {overflow}px（检查过宽的表格/图表/图片）"
                )

            # 2. 破损图片
            broken = page.evaluate(
                "[...document.images].filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src.slice(0, 60))"
            )
            for src in broken:
                issues.append(f"[image:{vname}] 图片加载失败: {src}")

            # 3. section 级内容溢出（块级裁切）
            clipped = page.evaluate(
                """[...document.querySelectorAll('.vr-section, .vr-hero, .vr-block')]
                   .filter(el => el.scrollWidth > el.clientWidth + 2)
                   .map(el => (el.id ? '#'+el.id : el.className).slice(0, 50) +
                        ' 溢出 ' + (el.scrollWidth - el.clientWidth) + 'px')"""
            )
            for c in clipped:
                # 容器内可滚动（如代码块）不算失败，降级为告警
                (warnings if "vr-prose" in c else issues).append(f"[clip:{vname}] {c}")

            # 4. 截图存证（仅桌面档做全页与分节截图）
            if vname == "desktop":
                page.screenshot(path=str(shot_dir / "full-page.png"), full_page=True)
                is_deck = page.locator(".vr-slide").count() > 0
                if is_deck:
                    # deck：逐页激活后截图（默认只显示当前页）
                    n = page.locator(".vr-slide").count()
                    for i in range(n):
                        sid = page.evaluate(
                            f"() => {{ document.querySelectorAll('.vr-slide').forEach(function(s, j){{ s.classList.toggle('vr-active', j === {i}); }}); return document.querySelectorAll('.vr-slide')[{i}].id || 'slide-{i}'; }}"
                        )
                        page.screenshot(path=str(shot_dir / f"{sid}.png"))
                    page.evaluate(
                        "document.querySelectorAll('.vr-slide').forEach(function(s, j){ s.classList.toggle('vr-active', j === 0); })"
                    )
                else:
                    sections = page.locator(".vr-section, .vr-hero")
                    for i in range(sections.count()):
                        el = sections.nth(i)
                        sid = el.get_attribute("id") or f"section-{i}"
                        try:
                            el.screenshot(path=str(shot_dir / f"{sid}.png"))
                        except Exception:
                            pass
            page.close()
        browser.close()

    status = "FAILED" if issues else ("WARNING" if warnings else "PASS")
    return {"status": status, "file": str(html_path), "errors": issues, "warnings": warnings,
            "screenshots": str(shot_dir), "viewports": [v[0] for v in VIEWPORTS]}


def main() -> int:
    parser = argparse.ArgumentParser(description="第三层质检：浏览器渲染检查（可选依赖）")
    parser.add_argument("html", help="渲染产物 HTML 路径")
    parser.add_argument("--json", help="检查结果 JSON 输出路径")
    parser.add_argument("--shots", default=None, help="截图目录（默认 <html目录>/qa/screenshots）")
    args = parser.parse_args()

    try:
        import playwright  # noqa: F401
    except ImportError:
        html_path = Path(args.html)
        shot_dir = Path(args.shots) if args.shots else html_path.parent / "qa" / "screenshots"
        shot = degraded_screenshots(html_path, shot_dir)
        if shot:
            print("SKIPPED — 未安装 playwright，已降级为系统浏览器无头截图"
                  "（仅人工目检，溢出/裂图自动判定不可用，不阻断交付）。")
            print(f"目检截图: {shot}")
        else:
            print("SKIPPED — 未安装 playwright（pip install playwright），且未找到可用系统浏览器。"
                  "本层为可选质检，不阻断交付；建议安装后复查视觉效果。")
        return 3

    html_path = Path(args.html)
    shot_dir = Path(args.shots) if args.shots else html_path.parent / "qa" / "screenshots"
    result = run_checks(html_path, shot_dir)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    for e in result["errors"]:
        print(f"  ✗ {e}")
    for w in result["warnings"]:
        print(f"  ⚠ {w}")
    print(f"{result['status']} — 截图: {result['screenshots']}")
    return {"PASS": 0, "WARNING": 1, "FAILED": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
