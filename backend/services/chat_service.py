"""对话与 Agent 编排服务：把 LangGraph 执行结果持久化并转成 API 响应。"""
from __future__ import annotations

import time

from backend.agent.graph import get_graph
from backend.agent.intent import INTENT_LABELS
from backend.core.config import settings
from backend.core.errors import AppError
from backend.core.log_utils import get_logger
from backend.database import conversation_repo
from backend.models.schemas import ChatRequest, ChatResponse, ConfirmRequest

logger = get_logger(__name__)


def _base_state(
    session_id: str, message: str, history: list[dict], req: ChatRequest | None = None
) -> dict:
    return {
        "session_id": session_id,
        "message": message,
        "history": history,
        "top_k": (req.top_k if req else settings.default_top_k),
        "retrieval_mode": (req.retrieval_mode if req else "hybrid"),
        "hybrid_weight": (req.hybrid_weight if req else settings.hybrid_weight),
        "use_rerank": (req.use_rerank if req else False),
        "trace": [], "errors": [], "tool_results": [], "sources": [],
        "needs_clarification": False, "clarifying_question": "",
        "pending_confirmation": None,
        "pending_intent": conversation_repo.get_pending_intent(session_id),
        "plan_index": 0,
        "started_at": time.perf_counter(),
    }


def _to_response(session_id: str, final: dict) -> ChatResponse:
    intent = final.get("intent", "unknown")
    return ChatResponse(
        session_id=session_id,
        answer=final.get("answer") or "系统未能生成回答，请重试。",
        intent=intent,
        intent_label=INTENT_LABELS.get(intent, "未知意图"),
        sources=final.get("sources") or [],
        trace=final.get("trace") or [],
        tool_results=final.get("tool_results") or [],
        pending_confirmation=final.get("pending_confirmation"),
        llm_mode=final.get("llm_mode") or settings.llm_mode,
        decision_source=final.get("decision_source") or "",
        plan_source=final.get("plan_source") or "",
        fallback=bool(final.get("fallback")),
        elapsed_ms=final.get("elapsed_ms") or 0.0,
    )


def chat(req: ChatRequest) -> ChatResponse:
    session = conversation_repo.ensure_session(req.session_id)
    session_id = session["session_id"]
    history = conversation_repo.history_for_llm(session_id, limit=8)
    state = _base_state(session_id, req.message, history, req)
    state["action"] = "chat"
    try:
        final = get_graph().invoke(state)
    except Exception as exc:
        logger.exception("Agent 工作流执行失败")
        raise AppError("对话处理失败", str(exc)) from exc
    conversation_repo.add_message(session_id, "user", req.message)
    response = _to_response(session_id, final)
    conversation_repo.add_message(
        session_id, "assistant", response.answer, intent=response.intent,
        sources=[item.model_dump() for item in response.sources],
        trace=[item.model_dump() for item in response.trace],
        tool_results=response.tool_results,
    )
    if not history:
        conversation_repo.touch_session(session_id, title=req.message[:24])
    return response


def confirm(req: ConfirmRequest) -> ChatResponse:
    session = conversation_repo.ensure_session(req.session_id)
    session_id = session["session_id"]
    history = conversation_repo.history_for_llm(session_id, limit=8)
    message = "确认创建工单" if req.confirm else "取消创建工单"
    state = _base_state(session_id, message, history)
    state.update({"action": "confirm", "confirm": req.confirm, "edits": req.edits or {}})
    try:
        final = get_graph().invoke(state)
    except Exception as exc:
        logger.exception("工单确认流程执行失败")
        raise AppError("工单确认处理失败", str(exc)) from exc
    conversation_repo.add_message(session_id, "user", message)
    response = _to_response(session_id, final)
    conversation_repo.add_message(
        session_id, "assistant", response.answer, intent=response.intent,
        sources=[item.model_dump() for item in response.sources],
        trace=[item.model_dump() for item in response.trace],
        tool_results=response.tool_results,
    )
    return response


def list_sessions(limit: int = 50) -> list[dict]:
    return conversation_repo.list_sessions(limit)


def session_messages(session_id: str) -> list[dict]:
    conversation_repo.ensure_session(session_id)
    return conversation_repo.get_messages(session_id)


def reset_session(session_id: str) -> dict:
    conversation_repo.ensure_session(session_id)
    conversation_repo.reset_session(session_id)
    return {"会话编号": session_id, "提示": "对话已重置，历史消息与待确认工单均已清除。"}


def delete_session(session_id: str) -> dict:
    conversation_repo.delete_session(session_id)
    return {"会话编号": session_id, "提示": "会话及其消息已删除。"}
