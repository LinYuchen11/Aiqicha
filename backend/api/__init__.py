"""API 路由汇总。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.api import chat, documents, evaluation, retrieval, system, tools_api

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(retrieval.router)
api_router.include_router(tools_api.router)
api_router.include_router(evaluation.router)

__all__ = ["api_router"]
