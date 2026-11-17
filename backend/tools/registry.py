"""工具注册表：模型逻辑与工具执行完全解耦，新增工具只需注册一个 ToolSpec。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from backend.core.errors import ToolError
from backend.database.tool_repo import log_tool
from backend.models.schemas import ToolInfo

_REGISTRY: dict[str, "ToolSpec"] = {}


@dataclass
class ToolSpec:
    name: str
    label: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BaseModel], dict]
    requires_confirmation: bool = False


def register(spec: ToolSpec) -> None:
    if spec.name in _REGISTRY:
        raise ValueError(f"工具重复注册：{spec.name}")
    _REGISTRY[spec.name] = spec


def get_spec(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def list_tool_infos() -> list[ToolInfo]:
    return [
        ToolInfo(
            name=spec.name,
            label=spec.label,
            description=spec.description,
            parameters=spec.args_model.model_json_schema(),
            requires_confirmation=spec.requires_confirmation,
        )
        for spec in _REGISTRY.values()
    ]


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(x) for x in error.get("loc", ()))
        parts.append(f"{location}：{error.get('msg', '参数不合法')}")
    return "；".join(parts)


def invoke(name: str, args: dict, session_id: str | None = None) -> dict:
    """统一执行入口：参数校验 → 真实函数执行 → 结果落库 → 返回给 Agent。"""
    started = time.perf_counter()
    spec = get_spec(name)
    if spec is None:
        raise ToolError(f"未注册的工具：{name}", "请从工具列表中选择合适的工具")
    raw_args = dict(args or {})
    try:
        validated = spec.args_model(**raw_args)
    except ValidationError as exc:
        detail = _format_validation_error(exc)
        log_tool(session_id, name, raw_args, None, "失败", detail, (time.perf_counter() - started) * 1000)
        raise ToolError("工具参数不完整或非法", detail) from exc
    except TypeError as exc:
        log_tool(session_id, name, raw_args, None, "失败", str(exc), (time.perf_counter() - started) * 1000)
        raise ToolError("工具参数格式错误", str(exc)) from exc

    try:
        result = spec.handler(validated)
        elapsed = (time.perf_counter() - started) * 1000
        log_tool(session_id, name, validated.model_dump(exclude_none=True), result, "成功", "", elapsed)
        return {
            "tool": name,
            "label": spec.label,
            "status": "成功",
            "result": result,
            "elapsed_ms": round(elapsed, 2),
        }
    except ToolError as exc:
        log_tool(session_id, name, validated.model_dump(exclude_none=True), None, "失败", exc.message, (time.perf_counter() - started) * 1000)
        raise
    except Exception as exc:
        log_tool(session_id, name, validated.model_dump(exclude_none=True), None, "失败", str(exc), (time.perf_counter() - started) * 1000)
        raise ToolError("工具执行异常", str(exc)) from exc
