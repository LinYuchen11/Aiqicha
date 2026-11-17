"""RAG 管线编排：Query 处理 → 检索 → 可选重排 → Prompt → LLM → 答案 + 真实来源。"""
from __future__ import annotations

import time

from backend.core.errors import LLMError
from backend.core.log_utils import get_logger
from backend.llm.client import LLMClient
from backend.llm.mock import extractive_answer, no_answer
from backend.models.schemas import SourceCitation
from backend.rag.cleaner import normalize_query
from backend.rag.prompt import build_answer_prompt
from backend.rag.retriever import RetrievalOutcome, search

logger = get_logger(__name__)


class RAGPipeline:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        hybrid_weight: float | None = None,
        rerank: bool = False,
        rerank_mode: str | None = None,
        collection: str = "default",
    ) -> RetrievalOutcome:
        return search(
            query=query, collection=collection, top_k=top_k, mode=mode,
            hybrid_weight=hybrid_weight, rerank=rerank, rerank_mode=rerank_mode,
        )

    def generate(self, query: str, outcome: RetrievalOutcome, history: list[dict]) -> tuple[str, str]:
        if not outcome.hits:
            return no_answer(query), self.llm.mode
        if self.llm.is_mock:
            return extractive_answer(query, outcome.hits), "mock"
        system, user = build_answer_prompt(query, outcome.hits, history)
        try:
            return self.llm.complete(system, user), "deepseek"
        except LLMError as exc:
            logger.warning("大模型调用失败，降级为抽取式并明确标注：%s", exc.message)
            fallback = (
                f"【大模型调用失败】{exc.message}。以下为检索到的原文摘录，仅供参考，"
                "不是模型生成的答案。\n\n"
            )
            return fallback + extractive_answer(query, outcome.hits), "mock-fallback"

    @staticmethod
    def to_sources(outcome: RetrievalOutcome) -> list[SourceCitation]:
        return [
            SourceCitation(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                doc_name=hit.doc_name,
                section=hit.section,
                page=hit.page,
                snippet=hit.snippet,
                score=hit.score,
                rank=hit.rank,
            )
            for hit in outcome.hits
        ]

    def answer(
        self,
        query: str,
        history: list[dict] | None = None,
        top_k: int = 5,
        mode: str = "hybrid",
        hybrid_weight: float | None = None,
        rerank: bool = False,
        collection: str = "default",
    ) -> dict:
        started = time.perf_counter()
        clean_query = normalize_query(query)
        outcome = self.retrieve(
            clean_query, top_k=top_k, mode=mode, hybrid_weight=hybrid_weight,
            rerank=rerank, collection=collection,
        )
        text, llm_mode = self.generate(clean_query, outcome, history or [])
        return {
            "query": clean_query,
            "answer": text,
            "llm_mode": llm_mode,
            "sources": self.to_sources(outcome),
            "outcome": outcome,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
