"""第一层质检（ADR-003）：JSON Schema 校验 + 稳定 ID 唯一性 + 白名单。

校验失败时禁止进入渲染阶段（"校验不过不产出文件"）。
"""

import json
import re
from pathlib import Path
from typing import List, Tuple

import jsonschema

from . import CHART_TYPES, LAYOUTS, SCHEMA_VERSION, THEMES

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
_SCHEMA_PATH = _SCHEMAS_DIR / "report.schema.json"
_SLIDE_SCHEMA_PATH = _SCHEMAS_DIR / "slide.schema.json"

_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class ValidationError(Exception):
    """聚合所有校验错误信息，一次性报告（带路径定位）。"""


def load_schema() -> dict:
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_slide_schema() -> dict:
    with open(_SLIDE_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _registry_with_report_schema():
    """slide.schema.json 通过 $ref 复用 report.schema.json 的块定义。"""
    from referencing import Registry, Resource

    return Registry().with_resource(
        "https://visual-report.dev/schemas/report.schema.json",
        Resource.from_contents(load_schema()),
    )


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

    _semantic_checks(plan.get("sections", []), "section", errors)
    return errors


def validate_slide(plan: dict) -> List[str]:
    """校验 slide-plan（幻灯片模式）。语义检查与报告共用。"""
    errors: List[str] = []
    validator = jsonschema.Draft7Validator(load_slide_schema(), registry=_registry_with_report_schema())
    for err in sorted(validator.iter_errors(plan), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"[schema] {path}: {err.message}")
    if errors:
        return errors
    _semantic_checks(plan.get("slides", []), "slide", errors)
    return errors


def _semantic_checks(units: List[dict], unit_label: str, errors: List[str]) -> None:
    """ID 唯一性 / 图片离线 / 图表对齐 / diagram 一致性 —— 报告与幻灯片共用。"""
    seen: dict = {}

    def check_id(id_: str, where: str) -> None:
        if not _ID_RE.match(id_):
            errors.append(f"[id] {where}: ID「{id_}」不符合规范 ^[a-z0-9]+(-[a-z0-9]+)*$")
            return
        if id_ in seen:
            errors.append(f"[id] {where}: ID「{id_}」与 {seen[id_]} 重复（ADR-007 要求全文档唯一）")
        else:
            seen[id_] = where

    for unit in units:
        uid = unit.get("id", "<missing>")
        check_id(uid, f"{unit_label}「{unit.get('title', uid)}」")
        for i, blk in enumerate(unit.get("blocks", [])):
            if "id" in blk:
                check_id(blk["id"], f"{unit_label} {uid} 第 {i + 1} 个块")
            if blk.get("type") == "image" and blk["src"].startswith(("http://", "https://")):
                errors.append(
                    f"[offline] {unit_label} {uid} 第 {i + 1} 个块: image.src 禁止外部地址 {blk['src'][:60]}，"
                    "请使用本地路径（构建期内嵌）"
                )
            elif blk.get("type") == "chart":
                _check_chart(blk, f"[chart] {unit_label} {uid} 第 {i + 1} 个块", errors)
            elif blk.get("type") == "diagram":
                _check_diagram(blk, f"[diagram] {unit_label} {uid} 第 {i + 1} 个块", errors)


def _check_chart(blk: dict, where: str, errors: List[str]) -> None:
    data = blk["data"]
    labels_n = len(data["labels"])
    if "series" in data and data["series"]:
        for s in data["series"]:
            if len(s["values"]) != labels_n:
                errors.append(
                    f"{where}: series「{s['name']}」有 {len(s['values'])} 个值，与 {labels_n} 个 label 不对齐"
                )
    elif len(data.get("values", [])) != labels_n:
        errors.append(f"{where}: values({len(data.get('values', []))}) 与 labels({labels_n}) 不对齐")


def _check_diagram(blk: dict, where: str, errors: List[str]) -> None:
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
                errors.append(f"{where}: 边的 {end}「{e[end]}」引用了不存在的节点")


def validate_plan(plan: dict) -> List[str]:
    """按结构自动路由：报告（sections）或幻灯片（slides）。"""
    return validate_slide(plan) if "slides" in plan else validate_report(plan)


def validate_report_or_raise(plan: dict) -> None:
    errors = validate_plan(plan)
    if errors:
        raise ValidationError("plan 校验失败（共 %d 处）：\n  - %s" % (len(errors), "\n  - ".join(errors)))
