"""第一层质检（ADR-003）：JSON Schema 校验 + 稳定 ID 唯一性 + 白名单。

校验失败时禁止进入渲染阶段（"校验不过不产出文件"）。
"""

import json
import re
from pathlib import Path
from typing import List, Tuple

import jsonschema

from . import CHART_TYPES, LAYOUTS, SCHEMA_VERSION, THEMES

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "report.schema.json"

_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class ValidationError(Exception):
    """聚合所有校验错误信息，一次性报告（带路径定位）。"""


def load_schema() -> dict:
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate_report(plan: dict) -> List[str]:
    """校验 report-plan。返回错误列表（空列表 = 通过）。

    校验项：
    1. JSON Schema（结构、枚举白名单、必填字段）
    2. section/block ID 格式与全文档唯一性（ADR-007）
    3. image.src 禁止外部 http(s)（离线约束前置检查）
    4. chart 数据完整性（labels 与 values/series 对齐）
    """
    errors: List[str] = []
    schema = load_schema()

    for err in sorted(jsonschema.Draft7Validator(schema).iter_errors(plan), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"[schema] {path}: {err.message}")

    if errors:
        return errors  # Schema 不过，后续检查无意义

    # ---- ID 唯一性 ----
    seen: dict = {}

    def check_id(kind: str, id_: str, where: str) -> None:
        if not _ID_RE.match(id_):
            errors.append(f"[id] {where}: ID「{id_}」不符合规范 ^[a-z0-9]+(-[a-z0-9]+)*$")
            return
        if id_ in seen:
            errors.append(f"[id] {where}: ID「{id_}」与 {seen[id_]} 重复（ADR-007 要求全文档唯一）")
        else:
            seen[id_] = where

    for sec in plan.get("sections", []):
        sid = sec.get("id", "<missing>")
        check_id("section", sid, f"section「{sec.get('title', sid)}」")
        for i, blk in enumerate(sec.get("blocks", [])):
            if "id" in blk:
                check_id("block", blk["id"], f"section {sid} 第 {i + 1} 个块")

    # ---- 图片离线约束 ----
    for sec in plan.get("sections", []):
        sid = sec.get("id", "<missing>")
        for i, blk in enumerate(sec.get("blocks", [])):
            if blk.get("type") == "image" and blk["src"].startswith(("http://", "https://")):
                errors.append(
                    f"[offline] section {sid} 第 {i + 1} 个块: image.src 禁止外部地址 {blk['src'][:60]}，"
                    "请使用本地路径（构建期内嵌）"
                )

    # ---- 图表数据对齐 ----
    for sec in plan.get("sections", []):
        sid = sec.get("id", "<missing>")
        for i, blk in enumerate(sec.get("blocks", [])):
            if blk.get("type") != "chart":
                continue
            data = blk["data"]
            labels_n = len(data["labels"])
            if "series" in data and data["series"]:
                for s in data["series"]:
                    if len(s["values"]) != labels_n:
                        errors.append(
                            f"[chart] section {sid} 第 {i + 1} 个块: series「{s['name']}」"
                            f"有 {len(s['values'])} 个值，与 {labels_n} 个 label 不对齐"
                        )
            elif len(data.get("values", [])) != labels_n:
                errors.append(
                    f"[chart] section {sid} 第 {i + 1} 个块: values({len(data.get('values', []))}) "
                    f"与 labels({labels_n}) 不对齐"
                )

    # ---- diagram：节点 ID 唯一、坐标不冲突、边引用存在 ----
    for sec in plan.get("sections", []):
        sid = sec.get("id", "<missing>")
        for i, blk in enumerate(sec.get("blocks", [])):
            if blk.get("type") != "diagram":
                continue
            where = f"[diagram] section {sid} 第 {i + 1} 个块"
            node_ids, cells = set(), set()
            for n in blk["nodes"]:
                if n["id"] in node_ids:
                    errors.append(f"{where}: 节点 ID「{n['id']}」重复")
                node_ids.add(n["id"])
                cell = tuple(n["at"])
                if cell in cells:
                    errors.append(f"{where}: 节点「{n['id']}」与另一节点同占网格 {list(cell)}")
                cells.add(cell)
            for e in blk.get("edges", []):
                for end in ("from", "to"):
                    if e[end] not in node_ids:
                        errors.append(
                            f"{where}: 边的 {end}「{e[end]}」引用了不存在的节点"
                        )

    return errors


def validate_report_or_raise(plan: dict) -> None:
    errors = validate_report(plan)
    if errors:
        raise ValidationError("report-plan 校验失败（共 %d 处）：\n  - %s" % (len(errors), "\n  - ".join(errors)))
