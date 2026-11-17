"""工具结果运行时来源校验。

架构上 tool_results 只由 tools/registry.py::invoke() 写入，但 AgentState 是普通
list[dict]，无法在类型层面阻止其它节点塞入伪造结果。这里在结果整合前做一次
结构校验：只有「已注册工具名 + 合法状态 + dict 结果 + 耗时」的条目才被采信，
其余一律丢弃并留痕，避免模型用普通文本伪装成工具执行成功。
"""
from __future__ import annotations

from backend.tools.registry import list_tool_infos

_ALLOWED_STATUS = {"成功", "失败"}


def sanitize_tool_results(results: list[dict] | None) -> tuple[list[dict], int]:
    """返回 (可信结果列表, 被丢弃条数)。"""
    valid_names = {info.name for info in list_tool_infos()}
    clean: list[dict] = []
    dropped = 0
    for item in results or []:
        trusted = (
            isinstance(item, dict)
            and item.get("tool") in valid_names
            and item.get("status") in _ALLOWED_STATUS
            and isinstance(item.get("result"), dict)
            and isinstance(item.get("elapsed_ms"), (int, float))
        )
        if trusted:
            clean.append(item)
        else:
            dropped += 1
    return clean, dropped
