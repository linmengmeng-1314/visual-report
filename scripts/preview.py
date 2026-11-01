#!/usr/bin/env python3
"""风格预览（ADR-010 Show-Don't-Tell）：同一份 plan 用多个主题渲染真实页面预览。

用户挑中后把 meta.theme 写回 plan，再走正式渲染流程。
预览必须用真实内容渲染——禁止占位文本、禁止出现 "preview/Option A" 字样。

用法：
    python scripts/preview.py report-plan.json                    # 全部主题
    python scripts/preview.py report-plan.json --themes corporate,minimal
    python scripts/preview.py report-plan.json -o previews/       # 输出目录
退出码：0 = 成功。
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual_report import THEMES                      # noqa: E402
from visual_report.render import render_report        # noqa: E402
from visual_report.validate import validate_report    # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="多主题真实预览")
    parser.add_argument("plan", help="report-plan.json 路径")
    parser.add_argument("--themes", default=",".join(THEMES), help="逗号分隔的主题列表")
    parser.add_argument("-o", "--output", default="previews", help="预览输出目录")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    errors = validate_report(plan)
    if errors:
        print("✗ plan 校验失败，预览拒绝生成：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    produced = []
    for theme in [t.strip() for t in args.themes.split(",") if t.strip()]:
        if theme not in THEMES:
            print(f"⚠ 跳过未知主题: {theme}", file=sys.stderr)
            continue
        themed = copy.deepcopy(plan)
        themed["meta"]["theme"] = theme
        out = out_dir / f"preview-{theme}.html"
        out.write_text(render_report(themed, plan_path.parent), encoding="utf-8")
        produced.append((theme, out))

    for theme, out in produced:
        print(f"✓ {out} — 浏览器打开对比，选定后将 meta.theme 设为 {theme}")
    print(f"\n共 {len(produced)} 份真实预览。选定后：修改 plan 的 meta.theme → 正式渲染。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
