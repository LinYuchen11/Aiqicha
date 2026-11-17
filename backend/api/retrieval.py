"""检索调试接口：真实调用检索器，返回分数、来源、重排前后对比。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.models.schemas import RetrievalRequest, RetrievalResponse
from backend.services.document_service import retrieval_test

router = APIRouter(prefix="/api/retrieval", tags=["检索调试"])


@router.post("/search", response_model=RetrievalResponse)
def search(req: RetrievalRequest) -> RetrievalResponse:
    payload = retrieval_test(
        query=req.query, top_k=req.top_k, mode=req.mode,
        hybrid_weight=req.hybrid_weight, rerank=req.rerank,
    )
    return RetrievalResponse(**payload)
