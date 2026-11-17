"""对话与会话接口：所有历史按 session_id 隔离并持久化。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.database.conversation_repo import create_session, get_pending
from backend.models.schemas import ChatRequest, ChatResponse, ConfirmRequest
from backend.services import chat_service

router = APIRouter(prefix="/api", tags=["智能助手"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    return chat_service.chat(req)


@router.post("/chat/confirm", response_model=ChatResponse)
def confirm(req: ConfirmRequest) -> ChatResponse:
    return chat_service.confirm(req)


@router.post("/sessions")
def new_session() -> dict:
    return {"会话": create_session()}


@router.get("/sessions")
def sessions(limit: int = 50) -> dict:
    return {"会话": chat_service.list_sessions(limit)}


@router.get("/sessions/{session_id}/messages")
def messages(session_id: str) -> dict:
    return {"消息": chat_service.session_messages(session_id)}


@router.get("/sessions/{session_id}/pending")
def pending(session_id: str) -> dict:
    """刷新页面后仍能恢复待确认工单，避免确认状态丢失。"""
    return {"待确认工单": get_pending(session_id)}


@router.post("/sessions/{session_id}/reset")
def reset(session_id: str) -> dict:
    return chat_service.reset_session(session_id)


@router.delete("/sessions/{session_id}")
def delete(session_id: str) -> dict:
    return chat_service.delete_session(session_id)
