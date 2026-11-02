"""修订管理（ADR-004/Phase 3）：检查点、节点级 diff、历史、回滚。

约定：
- `.visual-report/report-plan.json` 是唯一生效计划（Agent 只编辑它）
- 每次成功修订：validate → render → static_check 全过，才写入新 HTML + 快照 + 历史条目
- 任何一步失败：旧 HTML 原样保留（渲染失败回滚，V2 §7-7）
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent


class ReviseError(Exception):
    """修订流程失败（校验/渲染/质检未过），旧产物已保留。"""


def _section_id(plan: dict, index: int) -> str:
    try:
        return plan["sections"][index].get("id", f"sections[{index}]")
    except (IndexError, KeyError):
        return f"sections[{index}]"


def _humanize_path(plan: dict, path: str) -> str:
    """把 JSON 路径 sections/3/blocks/2/content 映射为 section-id/block-id/content。"""
    parts = [p for p in path.split("/") if p]
    out, in_sections, sec_idx, blk_idx = [], False, None, None
    for p in parts:
        if p == "sections":
            in_sections = True
            out.append(p)
            continue
        if in_sections and p.isdigit() and sec_idx is None:
            sec_idx = int(p)
            out[-1] = "sections{" + _section_id(plan, sec_idx) + "}"
            continue
        if in_sections and p == "blocks":
            blk_idx = None
            out.append(p)
            continue
        if in_sections and p.isdigit() and "blocks" in out and blk_idx is None:
            blk_idx = int(p)
            try:
                blk = plan["sections"][sec_idx]["blocks"][blk_idx]
                bid = blk.get("id", f"[{blk_idx}]")
            except (IndexError, KeyError, TypeError):
                bid = f"[{blk_idx}]"
            out[-1] = "blocks{" + bid + "}"
            continue
        out.append(p)
    return "/".join(out)


def diff_plans(old: dict, new: dict) -> dict:
    """节点级 diff：返回 {changed: [路径], added: [路径], removed: [路径]}（人读路径）。"""

    def walk(a, b, path, acc):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a:
                    acc["added"].append(f"{path}/{k}")
                elif k not in b:
                    acc["removed"].append(f"{path}/{k}")
                else:
                    walk(a[k], b[k], f"{path}/{k}", acc)
        elif isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                if i >= len(a):
                    acc["added"].append(f"{path}/{i}")
                elif i >= len(b):
                    acc["removed"].append(f"{path}/{i}")
                else:
                    walk(a[i], b[i], f"{path}/{i}", acc)
        elif a != b:
            acc["changed"].append(path)

    acc = {"changed": [], "added": [], "removed": []}
    walk(old, new, "", acc)
    return {
        "changed": [_humanize_path(new, p) for p in acc["changed"]],
        "added": [_humanize_path(new, p) for p in acc["added"]],
        "removed": [_humanize_path(new, p) for p in acc["removed"]],
    }


class RevisionManager:
    def __init__(self, plan_path: Path, output_html: Path, state_dir: Optional[Path] = None):
        self.plan_path = Path(plan_path)
        self.output_html = Path(output_html)
        self.state_dir = Path(state_dir) if state_dir else self.plan_path.parent / ".visual-report"
        self.snap_dir = self.state_dir / "history" / "snapshots"
        self.revisions_file = self.state_dir / "history" / "revisions.json"

    # ---- 历史 ----
    def load_revisions(self) -> dict:
        if self.revisions_file.is_file():
            return json.loads(self.revisions_file.read_text(encoding="utf-8"))
        return {"revisions": []}

    def _save_revisions(self, data: dict) -> None:
        self.revisions_file.parent.mkdir(parents=True, exist_ok=True)
        self.revisions_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )

    # ---- 主流程 ----
    def apply(self, note: str, base_dir: Optional[Path] = None) -> dict:
        """校验 + 渲染 + 质检，全过才落盘新产物与历史；失败抛 ReviseError（旧产物保留）。"""
        from .render import render_report
        from .validate import ValidationError, validate_report

        new_plan = json.loads(self.plan_path.read_text(encoding="utf-8"))

        # 1. 第一层校验
        errors = validate_report(new_plan)
        if errors:
            raise ReviseError("第一层校验失败，未渲染（旧 HTML 保留）：\n  - " + "\n  - ".join(errors))

        # 2. 渲染到临时文件（不碰正式产物；渲染异常按契约转 ReviseError，旧产物保留）
        try:
            html_str = render_report(new_plan, base_dir or self.plan_path.parent)
        except (ValidationError, ValueError, FileNotFoundError) as e:
            raise ReviseError(f"渲染失败，未生成文件（旧 HTML 保留）：{e}")
        tmp_html = self.output_html.with_suffix(".tmp.html")
        tmp_html.parent.mkdir(parents=True, exist_ok=True)
        # LF 固定换行：与渲染主产物字节一致（ADR-001；Windows 文本模式默认翻成 CRLF）
        tmp_html.write_text(html_str, encoding="utf-8", newline="\n")

        # 3. 第二层质检（临时产物）
        sys.path.insert(0, str(REPO / "scripts"))
        from static_check import inspect_html  # noqa: E402

        result = inspect_html(tmp_html)
        if result["status"] == "FAILED":
            tmp_html.unlink(missing_ok=True)
            raise ReviseError(
                "第二层质检失败，已丢弃新渲染（旧 HTML 保留）：\n  - " + "\n  - ".join(result["errors"])
            )

        # 4. 与上一版做节点 diff
        revisions = self.load_revisions()
        prev_version = revisions["revisions"][-1]["version"] if revisions["revisions"] else 0
        old_snapshot = self.snap_dir / f"v{prev_version}-plan.json"
        old_plan = (
            json.loads(old_snapshot.read_text(encoding="utf-8")) if old_snapshot.is_file() else None
        )
        diff = diff_plans(old_plan, new_plan) if old_plan else {
            "changed": ["<初始版本>"], "added": [], "removed": [],
        }

        # 5. 落盘：快照旧版（若有）→ 新 HTML 上位 → 追加历史
        if self.output_html.exists():
            self.snap_dir.mkdir(parents=True, exist_ok=True)
            (self.snap_dir / f"v{prev_version}.html").write_text(
                self.output_html.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
            )
            if not old_snapshot.is_file():
                # 首次修订时没有 plan 快照，从历史无法恢复——记录提示
                pass
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        (self.snap_dir / f"v{prev_version + 1}-plan.json").write_text(
            json.dumps(new_plan, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
        tmp_html.replace(self.output_html)

        entry = {
            "version": prev_version + 1,
            "description": note,
            "changedNodes": diff["changed"] + diff["added"] + diff["removed"],
            "diff": diff,
            "htmlBytes": self.output_html.stat().st_size,
            "qaStatus": result["status"],
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        }
        revisions["revisions"].append(entry)
        self._save_revisions(revisions)
        return entry

    # ---- 回滚 ----
    def rollback(self, to_version: Optional[int] = None) -> dict:
        revisions = self.load_revisions()["revisions"]
        if not revisions:
            raise ReviseError("没有可回滚的历史")
        target = to_version or (revisions[-2]["version"] if len(revisions) >= 2 else None)
        if target is None:
            raise ReviseError("只有初始版本，无可回滚目标")
        target = int(target)
        plans = [r["version"] for r in revisions]

        plan_snap = self.snap_dir / f"v{target}-plan.json"
        html_snap = self.snap_dir / f"v{target}.html"
        if not plan_snap.is_file():
            raise ReviseError(f"v{target} 无 plan 快照（可回滚版本：{plans}）")

        self.plan_path.write_text(plan_snap.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        if html_snap.is_file() and self.output_html.exists():
            self.output_html.write_text(html_snap.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

        revisions.append({
            "version": revisions[-1]["version"] + 1,
            "description": f"回滚到 v{target}",
            "changedNodes": ["<rollback>"],
            "diff": {"changed": [], "added": [], "removed": []},
            "htmlBytes": self.output_html.stat().st_size if self.output_html.exists() else 0,
            "qaStatus": "ROLLED_BACK",
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        })
        self._save_revisions({"revisions": revisions})
        return {"rolledBackTo": target}
