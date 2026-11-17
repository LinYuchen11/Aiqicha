"""任务规划：把复杂任务拆成可验证的步骤，并决定条件分支路由。

真实 DeepSeek 模式下，模型的 steps / needs_clarification 会真正影响执行路径，
不再只是写进 trace 的装饰文本；模型失败时回退规则并记录决策来源。
"""
from __future__ import annotations

from backend.core.log_utils import get_logger
from backend.llm.client import LLMClient
from backend.rag.prompt import build_plan_prompt

logger = get_logger(__name__)

RULE_STEPS = {
    "knowledge_query": ["理解问题并结合历史对话", "检索企业知识库", "整合资料生成带来源的答案"],
    "it_consult": ["识别故障或咨询主题", "检索 IT 服务规范与故障手册", "给出处理建议与来源"],
    "ticket_query": ["提取工单编号", "选择工单状态查询工具", "执行工具并汇总结果"],
    "ticket_create": ["收集故障类型、描述与联系方式", "生成待确认工单", "等待用户确认", "写入工单库并回传编号"],
    "multi_step": ["检索故障处理手册", "判断是否存在可行方案", "给出分步处理建议", "说明无解时如何创建工单"],
    "multi_tool": ["查询 IT 服务目录", "依据服务目录结果决定是否继续", "查询工单状态并汇总"],
    "chitchat": ["直接生成能力说明"],
    "unknown": ["返回能力边界说明"],
    "ticket_confirm": ["读取待确认工单", "校验用户确认结果", "调用工单创建工具", "回传工单编号"],
}

ROUTES = {
    "knowledge_query": "retrieve",
    "it_consult": "it_tool",
    "multi_step": "retrieve",
    "multi_tool": "tool",
    "ticket_query": "tool",
    "ticket_create": "collect",
    "ticket_confirm": "confirm",
    "chitchat": "direct",
    "unknown": "direct",
}

# 复杂任务才调用模型规划，避免简单闲聊也额外产生一次 API 调用
COMPLEX_INTENTS = {"multi_step", "multi_tool", "ticket_create", "knowledge_query", "it_consult"}


def plan_steps(intent: str, message: str, slots: dict, llm: LLMClient | None = None) -> dict:
    """规则步骤为基线；真实模型结构化输出可覆盖步骤并驱动追问分支。"""
    client = llm or LLMClient()
    steps = list(RULE_STEPS.get(intent, RULE_STEPS["unknown"]))
    source = "规则规划器"
    fallback = False
    needs_clarification = False
    clarifying_question = ""
    if not client.is_mock and intent in COMPLEX_INTENTS:
        system, user = build_plan_prompt(message, intent, slots)
        try:
            data = client.complete_json(system, user)
            produced = [str(s) for s in (data.get("steps") or []) if str(s).strip()]
            if produced:
                steps = produced
                source = "DeepSeek 结构化规划"
            if bool(data.get("needs_clarification")) and str(data.get("clarifying_question") or "").strip():
                needs_clarification = True
                clarifying_question = str(data["clarifying_question"]).strip()
        except Exception as exc:
            fallback = True
            logger.warning("模型任务规划失败，回退规则规划器：%s", exc)
    return {
        "steps": steps,
        "route": ROUTES.get(intent, "direct"),
        "source": source,
        "fallback": fallback,
        "needs_clarification": needs_clarification,
        "clarifying_question": clarifying_question,
    }


def route_by_intent(state: dict) -> str:
    """模型规划判定需要追问时，真正改变执行路径（走信息收集节点）。"""
    if state.get("needs_clarification") and state.get("clarifying_question"):
        return "collect"
    return state.get("route", "direct")


def route_after_retrieve(state: dict) -> str:
    return "multi" if state.get("intent") == "multi_step" else "integrate"


def route_after_tool(state: dict) -> str:
    """依据前一步工具返回的结果内容决定下一步，而不是只看意图固定跳转。"""
    results = state.get("tool_results") or []
    last = results[-1] if results else None
    succeeded = bool(last and last.get("status") == "成功")
    payload = (last or {}).get("result") or {}

    if state.get("intent") == "it_consult":
        # 服务目录查询成功才继续检索知识库；失败直接整合错误说明
        return "retrieve" if succeeded else "integrate"

    if state.get("intent") == "multi_tool":
        # 第一步查到匹配服务且计划还有下一步 → 回边继续执行第二个工具
        has_items = bool(payload.get("found")) and bool(payload.get("items"))
        if succeeded and has_items and state.get("plan_index", 0) < 2:
            return "next_tool"
        return "integrate"

    return "integrate"
