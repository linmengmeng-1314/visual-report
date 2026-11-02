"""第一层质检（ADR-003）：JSON Schema 校验 + 稳定 ID 唯一性 + 白名单。

校验失败时禁止进入渲染阶段（"校验不过不产出文件"）。
"""

import json
import re
from pathlib import Path
from typing import List, Tuple

import jsonschema
from jsonschema.exceptions import best_match

from . import CHART_TYPES, LAYOUTS, SCHEMA_VERSION, THEMES
from .diagram import direction_warnings, lint_diagram, width_warnings

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


def _leaves(err) -> list:
    """收集错误子树全部叶子错误（无 context 即叶子）。"""
    if not err.context:
        return [err]
    out = []
    for sub in err.context:
        out.extend(_leaves(sub))
    return out


def _schema_errors(validator, plan: dict) -> List[str]:
    """Schema 错误统一格式化：oneOf/anyOf 聚合错误下钻到最相关变体（best_match）。

    jsonschema 把所有不匹配变体的错误平铺进 context，best_match 只返回最相关一片——
    同块的其他违规会被吞掉（修一个、验一次、再冒一个，返工翻倍）；而无脑收全
    又会把其余变体的 type/const 噪音放进来。折中：best_match 只用来「选变体」，
    按 schema_path 首段（变体下标）过滤，收全该变体的所有叶子。

    输出形如 sections/2/blocks/0/nodes/3/label: ... too long（实际 47 > 上限 40）。
    """
    rows = []
    for err in validator.iter_errors(plan):
        best = best_match([err])
        if err.context and best.schema_path:
            variant = best.schema_path[0]
            picked = [l for l in _leaves(err) if l.schema_path and l.schema_path[0] == variant]
        else:
            picked = [best]
        for leaf in picked:
            msg = leaf.message
            if leaf.validator == "maxLength":  # 默认消息不带数量，补上「实际 N > 上限 M」便于直接定位
                msg += f"（实际 {len(leaf.instance)} > 上限 {leaf.validator_value}）"
            rows.append((list(leaf.absolute_path), msg))
    rows.sort(key=lambda r: r[0])
    errors, seen = [], set()
    for path, msg in rows:
        loc = "/".join(str(p) for p in path) or "<root>"
        line = f"[schema] {loc}: {msg}"
        if line not in seen:
            seen.add(line)
            errors.append(line)
    return errors


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

    errors.extend(_schema_errors(jsonschema.Draft7Validator(schema), plan))
    if errors:
        return errors  # Schema 不过，后续检查无意义

    _semantic_checks(plan.get("sections", []), "section", errors)
    return errors


def validate_slide(plan: dict) -> List[str]:
    """校验 slide-plan（幻灯片模式）。语义检查与报告共用。"""
    errors: List[str] = []
    validator = jsonschema.Draft7Validator(load_slide_schema(), registry=_registry_with_report_schema())
    errors.extend(_schema_errors(validator, plan))
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
    consistent = True
    for e in blk.get("edges", []):
        if e["from"] == e["to"]:
            errors.append(f"{where}: 自环边「{e['from']}」→ 自己，不支持")
            consistent = False
        for end in ("from", "to"):
            if e[end] not in node_ids:
                errors.append(f"{where}: 边的 {end}「{e[end]}」引用了不存在的节点")
                consistent = False
    if consistent:
        # 几何 lint（diagram 2.0）：穿盒 / 标签压线 / 拐点数 / 短线段，
        # 与渲染共用同一套布线（确定性），校验阶段即可预判
        for issue in lint_diagram(blk["nodes"], blk.get("edges", [])):
            errors.append(f"{where}: {issue}")


def validate_plan(plan: dict) -> List[str]:
    """按结构自动路由：报告（sections）或幻灯片（slides）。"""
    return validate_slide(plan) if "slides" in plan else validate_report(plan)


def plan_warnings(plan: dict) -> List[str]:
    """建议级诊断（不阻断渲染）：主链方向一致性（B1）等。报告与幻灯片共用。"""
    units = plan.get("slides", plan.get("sections", []))
    out: List[str] = []
    for unit in units:
        uid = unit.get("id", "<missing>")
        for i, blk in enumerate(unit.get("blocks", [])):
            if blk.get("type") == "diagram":
                advise = direction_warnings(
                    blk["nodes"], blk.get("edges", []), blk.get("direction", "lr")
                ) + width_warnings(blk["nodes"], bool(unit.get("wide")))
                out.extend(f"[diagram] {uid} 第 {i + 1} 个块: {a}" for a in advise)
    return out


def validate_report_or_raise(plan: dict) -> None:
    errors = validate_plan(plan)
    if errors:
        raise ValidationError("plan 校验失败（共 %d 处）：\n  - %s" % (len(errors), "\n  - ".join(errors)))
