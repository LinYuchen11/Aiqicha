"""LangGraph 工作流状态定义。各节点返回局部更新，由 LangGraph 合并到状态。"""
from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    action: str                      # chat | confirm
    message: str
    resolved_query: str
    history: list[dict]
    top_k: int
    retrieval_mode: str
    hybrid_weight: float
    use_rerank: bool

    intent: str
    intent_label: str
    intent_source: str
    decision_source: str          # 意图决策来源：DeepSeek 结构化输出 / 规则决策器 / 模型失败回退
    plan_source: str              # 任务规划来源：DeepSeek 结构化规划 / 规则规划器
    fallback: bool                # 本次是否发生模型→规则回退
    slots: dict[str, Any]
    plan: list[str]
    route: str
    tool_queue: list[dict[str, Any]]  # 多工具连续执行的规划队列
    plan_index: int                   # 当前执行到第几个工具
    pending_intent: str | None        # 上一轮挂起的意图，用于追问恢复

    trace: list[dict[str, Any]]
    errors: list[str]
    outcome: Any
    sources: list[Any]

    selected_tool: str | None
    tool_args: dict[str, Any]
    tool_results: list[dict[str, Any]]
    needs_clarification: bool
    clarifying_question: str
    pending_confirmation: dict[str, Any] | None
    multi_step_note: str

    confirm: bool
    edits: dict[str, Any]
    answer: str
    llm_mode: str
    elapsed_ms: float
    started_at: float
