#!/usr/bin/env python3
"""第一层质检（ADR-003）：校验 report-plan.json，不过则禁止渲染。

用法：
    python scripts/validate.py report-plan.json
退出码：0 = PASS，2 = FAILED。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual_report.validate import validate_plan  # noqa: E402

# 中文 Windows 控制台重定向输出时按 GBK 编码，✓/✗ 等符号会触发 UnicodeEncodeError——统一切 UTF-8（Mac/Linux 已是 UTF-8，此段无操作）
for _s in (sys.stdout, sys.stderr):
    _rc = getattr(_s, "reconfigure", None)
    if _rc and getattr(_s, "encoding", "").lower().replace("-", "") != "utf8":
        _rc(encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/validate.py <plan.json>", file=sys.stderr)
        return 1
    path = Path(sys.argv[1])
    plan = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_plan(plan)
    if errors:
        print(f"FAILED — {len(errors)} 处问题：")
        for e in errors:
            print(f"  ✗ {e}")
        return 2
    if "slides" in plan:
        print(f"PASS — {len(plan['slides'])} 页幻灯片，ID 唯一，白名单校验通过")
    else:
        print(f"PASS — {len(plan['sections'])} 个 section，ID 唯一，白名单校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
