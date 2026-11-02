#!/usr/bin/env python3
"""修订 CLI（Phase 3）：改 plan 后一键「校验 → 渲染 → 质检 → 快照 → 记历史」。

用法：
    python scripts/revise.py apply report-plan.json -o output/visual-report.html --note "调整架构图方向"
    python scripts/revise.py log   report-plan.json            # 查看修订历史
    python scripts/revise.py rollback report-plan.json -o output/visual-report.html [--to 2]

退出码：0 成功 / 2 失败（旧产物保留）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual_report.project import ReviseError, RevisionManager  # noqa: E402

# 中文 Windows 控制台重定向输出时按 GBK 编码，✓/✗ 等符号会触发 UnicodeEncodeError——统一切 UTF-8（Mac/Linux 已是 UTF-8，此段无操作）
for _s in (sys.stdout, sys.stderr):
    _rc = getattr(_s, "reconfigure", None)
    if _rc and getattr(_s, "encoding", "").lower().replace("-", "") != "utf8":
        _rc(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查点修订闭环")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_apply = sub.add_parser("apply", help="校验+渲染+质检+快照+历史（失败保留旧产物）")
    p_apply.add_argument("plan", help="report-plan.json 路径")
    p_apply.add_argument("-o", "--output", default="output/visual-report.html")
    p_apply.add_argument("--note", required=True, help="本次修改说明（写进历史）")

    p_log = sub.add_parser("log", help="查看修订历史")
    p_log.add_argument("plan", help="report-plan.json 路径")

    p_rb = sub.add_parser("rollback", help="回滚到历史版本")
    p_rb.add_argument("plan", help="report-plan.json 路径")
    p_rb.add_argument("-o", "--output", default="output/visual-report.html")
    p_rb.add_argument("--to", type=int, default=None, help="目标版本（默认上一版）")

    args = parser.parse_args()
    plan = Path(args.plan)

    if args.cmd == "log":
        mgr = RevisionManager(plan, plan.parent / "output" / "visual-report.html")
        revisions = mgr.load_revisions()["revisions"]
        if not revisions:
            print("（暂无修订历史）")
            return 0
        for r in revisions:
            print(f"v{r['version']}  {r['createdAt']}  {r['description']}")
            for n in r.get("changedNodes", [])[:8]:
                print(f"        · {n}")
            if len(r.get("changedNodes", [])) > 8:
                print(f"        · …共 {len(r['changedNodes'])} 处")
        return 0

    mgr = RevisionManager(plan, Path(args.output))
    try:
        if args.cmd == "apply":
            entry = mgr.apply(args.note)
            print(f"✓ v{entry['version']} 已生效 — {entry['description']}")
            print(f"  产物: {args.output} ({entry['htmlBytes'] / 1024:.0f} KB, QA {entry['qaStatus']})")
            changed = entry["diff"]["changed"] + entry["diff"]["added"] + entry["diff"]["removed"]
            print(f"  变更 {len(changed)} 处：")
            for c in changed[:10]:
                print(f"    · {c}")
            if len(changed) > 10:
                print(f"    · …共 {len(changed)} 处")
        elif args.cmd == "rollback":
            result = mgr.rollback(args.to)
            print(f"✓ 已回滚到 v{result['rolledBackTo']}（plan 与 HTML 同步恢复）")
    except ReviseError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
