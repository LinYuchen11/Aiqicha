"""Pydantic 数据契约：API 入参与出参、工具参数、评估记录。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

RetrievalMode = Literal["vector", "keyword", "hybrid"]


class DocumentInfo(BaseModel):
    id: str
    filename: str
    file_type: str
    size_bytes: int
    sha256: str
    status: str
    chunk_count: int = 0
    error_msg: str | None = None
    is_sample: bool = False
    created_at: str
    updated_at: str


class ChunkInfo(BaseModel):
    id: str
    doc_id: str
    chunk_index: int
    text: str
    section: str | None = None
    page: int | None = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    section: str | None = None
    page: int | None = None
    text: str
    snippet: str
    score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0
    rank: int
    rerank_score: float | None = None
    original_rank: int | None = None


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: RetrievalMode = "hybrid"
    hybrid_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    rerank: bool = False
    collection: str = Field(default="default", min_length=1, max_length=80)

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("问题内容不能为空")
        return v


class RetrievalResponse(BaseModel):
    query: str
    mode: RetrievalMode
    top_k: int
    hybrid_weight: float
    rerank_applied: bool
    total_vectors: int
    results: list[RetrievedChunk]
    elapsed_ms: float
    message: str = ""


class SourceCitation(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    section: str | None = None
    page: int | None = None
    snippet: str
    score: float
    rank: int


class TraceStep(BaseModel):
    stage: str
    detail: str
    tool: str | None = None
    args_summary: str | None = None
    result: str | None = None
    elapsed_ms: float | None = None
    decision_source: str | None = None  # 该步骤的决策来自模型还是规则


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: RetrievalMode = "hybrid"
    hybrid_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    use_rerank: bool = False

    @field_validator("message")
    @classmethod
    def strip_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息内容不能为空")
        return v


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    intent: str
    intent_label: str
    sources: list[SourceCitation] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    pending_confirmation: dict[str, Any] | None = None
    llm_mode: str
    decision_source: str = ""   # 意图决策来源（模型 / 规则 / 回退）
    plan_source: str = ""       # 任务规划来源（模型 / 规则）
    fallback: bool = False      # 本次是否发生模型失败回退
    elapsed_ms: float


class ConfirmRequest(BaseModel):
    session_id: str = Field(min_length=1)
    confirm: bool
    edits: dict[str, Any] = Field(default_factory=dict)


class ToolInvokeRequest(BaseModel):
    tool_name: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class ToolInfo(BaseModel):
    name: str
    label: str
    description: str
    parameters: dict[str, Any]
    requires_confirmation: bool = False


class EvalRunRequest(BaseModel):
    experiment: Literal["chunking", "topk", "retrieval", "rerank", "embedding"]
    params: dict[str, Any] = Field(default_factory=dict)


class HumanEvalRequest(BaseModel):
    run_id: str | None = None
    question_id: str
    answer_correctness: float | None = Field(default=None, ge=0, le=1)
    citation_accuracy: float | None = Field(default=None, ge=0, le=1)
    note: str = ""
    evaluator: str = "人工评估"
