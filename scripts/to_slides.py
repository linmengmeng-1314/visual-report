#!/usr/bin/env python3
"""报告 → 幻灯片转换脚手架（Phase 4d）。

确定性部分交给脚本：KPI/图表/架构图/表格直接复用，正文降级为演讲备注，
长文按句子抽要点生成 bullets 草稿。
叙事精炼交给 Agent：按宣讲时长删并页面、重写 action title、控制信息密度。

用法：
    python scripts/to_slides.py report-plan.json -o slide-plan.json [--theme tech] [--minutes 15]
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual_report.validate import validate_plan  # noqa: E402

# 中文 Windows 控制台重定向输出时按 GBK 编码，✓/✗ 等符号会触发 UnicodeEncodeError——统一切 UTF-8（Mac/Linux 已是 UTF-8，此段无操作）
for _s in (sys.stdout, sys.stderr):
    _rc = getattr(_s, "reconfigure", None)
    if _rc and getattr(_s, "encoding", "").lower().replace("-", "") != "utf8":
        _rc(encoding="utf-8")


def _sentences(md_text: str, limit: int = 4) -> list:
    """从 Markdown 提取前 N 个要点：优先列表项，其次按句号切分。"""
    lines = [l.strip().lstrip("-*· ").strip() for l in md_text.splitlines()]
    bullets = [re.sub(r"[*`]", "", l) for l in lines if l and not l.startswith("#")]
    if len(bullets) >= 2:
        return bullets[:limit]
    plain = re.sub(r"[*`#\n]", " ", md_text)
    sents = [s.strip() for s in re.split(r"[。；;.!?！？]", plain) if len(s.strip()) >= 6]
    return sents[:limit]


def _strip_md(md_text: str, limit: int = 200) -> str:
    plain = re.sub(r"[*`#>\n]", " ", md_text)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit] + ("…" if len(plain) > limit else "")


def transform(report: dict, theme: str = None, minutes: int = 15) -> dict:
    meta = dict(report["meta"])
    if theme:
        meta["theme"] = theme
    meta["footer"] = meta.get("footer") or meta["title"]

    slides = []
    # 报告里的 section/block ID 全部保留——复用块会带着原 ID 进 deck，slide ID 不得与之撞名
    used_ids = {sec["id"] for sec in report["sections"]}
    for sec in report["sections"]:
        used_ids.update(b["id"] for b in sec.get("blocks", []) if b.get("id"))

    def sid(base: str) -> str:
        i, candidate = 1, base
        while candidate in used_ids:
            i += 1
            candidate = f"{base}-{i}"
        used_ids.add(candidate)
        return candidate

    for sec in report["sections"]:
        layout = sec["layout"]
        title = sec["title"]

        if layout == "hero":
            slide = {
                "id": sid(sec["id"]),
                "layout": "title",
                "title": title,
                "subtitle": sec.get("subtitle") or meta.get("subtitle", ""),
            }
            kpis = [b for b in sec.get("blocks", []) if b.get("type") == "kpi"]
            notes_parts = []
            if kpis:
                slides.append(slide)
                kpi_slide = {
                    "id": sid(f"{sec['id']}-kpis"),
                    "layout": "kpi",
                    "kicker": "结果",
                    "title": "四个关键数字",
                    "blocks": kpis,
                    "notes": "由报告封面 KPI 直接复用。精炼建议：标题改写为结论式（如『自动化率破 60%，成本反降 14%』），按汇报重点排序并精简到 ≤4 个。",
                }
                slides.append(kpi_slide)
            else:
                slides.append(slide)
            continue

        if layout == "conclusion":
            texts = [b for b in sec.get("blocks", []) if b.get("type") in ("callout", "text")]
            gist = _strip_md(texts[0]["content"]) if texts else sec.get("subtitle", "")
            slides.append({
                "id": sid(sec["id"]),
                "layout": "statement",
                "title": title,
                "subtitle": gist,
                "notes": "结论页：把报告结论压缩成一句话。" + (
                    f"原文：{_strip_md(texts[0]['content'], 400)}" if texts else ""),
            })
            continue

        # 其余 section：kicker 保留，版式按内容推断
        kicker = sec.get("kicker")
        reusable = []   # 可直接复用的块
        texts = []
        for b in sec.get("blocks", []):
            if b.get("type") in ("kpi", "chart", "diagram", "table", "columns", "quote"):
                reusable.append(b)
            elif b.get("type") in ("text", "list", "cards"):
                texts.append(b)

        # 章节内容 > 1 个可复用块时先给一页分隔页（长 deck 节奏用，Agent 可删）
        if len(reusable) + len(texts) >= 3 and len(report["sections"]) > 5:
            slides.append({
                "id": sid(f"{sec['id']}-divider"),
                "layout": "section",
                "kicker": kicker or "",
                "title": title,
                "subtitle": sec.get("subtitle", ""),
            })

        text_notes = "\n".join(
            f"[原文·{t['type']}] {t['content'] if t['type'] == 'text' else json.dumps(t.get('items', []), ensure_ascii=False)}"
            for t in texts
        )

        if reusable:
            for b in reusable:
                slide_layout = {
                    "kpi": "kpi", "chart": "chart", "diagram": "diagram",
                    "table": "table", "columns": "two-col", "quote": "quote",
                }[b["type"]]
                slide = {
                    "id": sid(f"{sec['id']}-{b.get('id', b['type'])}"),
                    "layout": slide_layout,
                    "kicker": kicker,
                    "title": title,
                    "blocks": [b],
                }
                if text_notes:
                    slide["notes"] = text_notes
                slides.append(slide)
        elif texts:
            first_text = texts[0]
            content = first_text.get("content") or "\n".join(first_text.get("items", []))
            slides.append({
                "id": sid(sec["id"]),
                "layout": "bullets",
                "kicker": kicker,
                "title": title,
                "blocks": [{"type": "list", "items": _sentences(content) or ["（待精炼要点）"]}],
                "notes": "正文已自动降级为要点草稿，需按宣讲口径精炼：\n" + text_notes,
            })

    # 清理：剔除值为 None 的可选字段（kicker/subtitle 等可能缺失）
    for s in slides:
        for k in list(s.keys()):
            if s[k] is None:
                del s[k]

    # 页数预算提示（15 分钟 ≈ 10 页）
    return {
        "$schema": "https://visual-report.dev/schemas/slide.schema.json",
        "meta": meta,
        "slides": slides,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="报告 → 幻灯片骨架转换")
    parser.add_argument("plan", help="report-plan.json 路径")
    parser.add_argument("-o", "--output", required=True, help="slide-plan.json 输出路径")
    parser.add_argument("--theme", default=None, help="覆盖主题（如 tech）")
    parser.add_argument("--minutes", type=int, default=15, help="宣讲时长（页数预算参考）")
    args = parser.parse_args()

    report = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    deck = transform(report, theme=args.theme, minutes=args.minutes)

    errors = validate_plan(deck)
    if errors:
        print("✗ 生成的骨架未通过校验（这是 bug，请提 issue）：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    out = Path(args.output)
    out.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    budget = max(5, round(args.minutes / 1.5))
    print(f"✓ {out} — {len(deck['slides'])} 页（{args.minutes} 分钟建议 ≤{budget} 页）")
    print("下一步（Agent 精炼）：删并页面到页数预算 · 重写每页标题为结论式 · 精炼 bullets · 检查 notes 演讲口径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
