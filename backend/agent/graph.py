"""LangGraph 有状态工作流：意图 → 规划 → 条件分支 → 工具/检索 → 整合 → 回答。

简单知识查询只经过必要节点；多步骤任务走额外判定分支；工单创建必须经过
「信息收集 → 待确认 → 用户确认 → 工具写库」的挂起/恢复流程。
"""
from __future__ import annotations

from langgraph.graph import StateGraph

try:
    from langgraph.graph import END
except ImportError:
    from langgraph.constants import END

from backend.agent import nodes
from backend.agent.planner import route_after_retrieve, route_after_tool, route_by_intent
from backend.agent.state import AgentState

_graph = None


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("intent", nodes.intent_node)
    builder.add_node("planner", nodes.planner_node)
    builder.add_node("retrieve", nodes.retrieve_node)
    builder.add_node("tool_select", nodes.tool_select_node)
    builder.add_node("tool_execute", nodes.tool_execute_node)
    builder.add_node("collect_info", nodes.collect_info_node)
    builder.add_node("confirm", nodes.confirm_node)
    builder.add_node("multi_step", nodes.multi_step_node)
    builder.add_node("integrate", nodes.integrate_node)
    builder.add_node("final", nodes.final_node)

    builder.set_entry_point("intent")
    builder.add_edge("intent", "planner")
    builder.add_conditional_edges(
        "planner", route_by_intent,
        {
            "retrieve": "retrieve",
            "it_tool": "tool_select",
            "tool": "tool_select",
            "collect": "collect_info",
            "confirm": "confirm",
            "direct": "integrate",
        },
    )
    builder.add_edge("tool_select", "tool_execute")
    builder.add_conditional_edges(
        "tool_execute", route_after_tool,
        {
            "retrieve": "retrieve",
            "integrate": "integrate",
            # 受控回边：多工具连续执行，是否继续由前一步工具结果决定
            "next_tool": "tool_select",
        },
    )
    builder.add_conditional_edges(
        "retrieve", route_after_retrieve,
        {"multi": "multi_step", "integrate": "integrate"},
    )
    builder.add_edge("collect_info", "integrate")
    builder.add_edge("confirm", "integrate")
    builder.add_edge("multi_step", "integrate")
    builder.add_edge("integrate", "final")
    builder.add_edge("final", END)
    return builder.compile()


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
