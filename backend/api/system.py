"""系统状态与配置接口（配置信息已脱敏）。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.core.config import settings
from backend.database.document_repo import stats
from backend.database.tool_repo import tool_stats
from backend.llm.client import LLMClient
from backend.rag import model_guard
from backend.rag.embeddings import embedding_info
from backend.rag.vectorstore import get_vector_store

router = APIRouter(prefix="/api", tags=["系统状态"])


@router.get("/health")
def health() -> dict:
    store = get_vector_store()
    return {
        "状态": "运行正常",
        "系统名称": "通用企业级智能知识管理与任务助手",
        "是否为模拟运行": settings.is_mock,
        "大模型": LLMClient().health(),
        "向量方案": embedding_info(),
        "向量库一致性": model_guard.compatibility_status("default"),
        "向量库": store.name,
        "向量数量": store.count("default"),
        "文档统计": stats(),
        "工具调用统计": tool_stats(),
    }


@router.get("/config")
def config() -> dict:
    return {
        "当前配置": settings.public_dict(),
        "运行说明": (
            "当前为 Mock 模拟运行：界面、检索与工具调用均为真实逻辑，"
            "答案由本地抽取式模拟器基于检索片段生成，不是大模型输出。"
            if settings.is_mock else
            "当前为 DeepSeek 真实模型运行：请确保 .env 中的 API Key 有效。"
        ),
    }
