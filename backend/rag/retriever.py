"""检索器：向量相似度、BM25 关键词、加权混合检索，以及可选重排序。"""
from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from backend.core.config import settings
from backend.core.errors import VectorError
from backend.core.log_utils import get_logger
from backend.models.schemas import RetrievedChunk
from backend.rag import model_guard
from backend.rag.cleaner import normalize_query, tokenize_for_search
from backend.rag.embeddings import get_embedder
from backend.rag.rerank import apply_rerank
from backend.rag.vectorstore import get_vector_store

logger = get_logger(__name__)
_K1, _B = 1.5, 0.75
# 无答案判据：同时满足「命中二元字组数 < 4」「最大覆盖率 < 0.30」
# 「最高原始余弦相似度 < 0.5」才判定资料不足。
# 实测（6 份模拟文档 / 24 条测试问题）：有答案问题命中 4~17 个、覆盖率 0.31~0.55；
# 无答案问题命中 2~3 个、覆盖率 0.13~0.20。使用「命中数 OR 覆盖率」双通道，
# 避免上下文改写拉长查询后覆盖率被稀释而误杀连续追问。
_NO_ANSWER_MIN_HITS = 4
_NO_ANSWER_COVERAGE = 0.30
_NO_ANSWER_SIMILARITY = 0.5


@dataclass
class RetrievalOutcome:
    query: str
    mode: str
    top_k: int
    hybrid_weight: float
    hits: list[RetrievedChunk] = field(default_factory=list)
    total_vectors: int = 0
    elapsed_ms: float = 0.0
    rerank_applied: bool = False
    rerank_method: str = "未启用"
    message: str = ""


def _cosine_matrix(matrix: np.ndarray, query_vec: np.ndarray) -> np.ndarray:
    matrix_norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0 or matrix_norm.size == 0:
        return np.zeros(len(matrix), dtype=np.float64)
    denom = np.maximum(matrix_norm.flatten() * q_norm, 1e-12)
    return (matrix @ query_vec) / denom


def _bm25(query_tokens: list[str], docs: list[list[str]]) -> list[float]:
    if not docs:
        return []
    tfs = [Counter(doc) for doc in docs]
    lengths = [sum(tf.values()) or 1 for tf in tfs]
    avgdl = sum(lengths) / len(lengths)
    unique_q = set(query_tokens)
    df: dict[str, int] = {}
    for token in unique_q:
        df[token] = sum(1 for tf in tfs if token in tf)
    scores: list[float] = []
    for tf, dl in zip(tfs, lengths):
        score = 0.0
        for token in unique_q:
            freq = tf.get(token, 0)
            if not freq:
                continue
            idf = math.log(1 + (len(docs) - df[token] + 0.5) / (df[token] + 0.5))
            score += idf * (freq * (_K1 + 1)) / (freq + _K1 * (1 - _B + _B * dl / avgdl))
        scores.append(score)
    return scores


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return [0.0 for _ in values]
    return [(v - low) / (high - low) for v in values]


def _snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


def search(
    query: str,
    collection: str = "default",
    top_k: int | None = None,
    mode: str = "hybrid",
    hybrid_weight: float | None = None,
    rerank: bool = False,
    rerank_mode: str | None = None,
) -> RetrievalOutcome:
    started = time.perf_counter()
    q = normalize_query(query)
    k = top_k or settings.default_top_k
    w = settings.hybrid_weight if hybrid_weight is None else hybrid_weight
    outcome = RetrievalOutcome(query=q, mode=mode, top_k=k, hybrid_weight=w)

    # 检索前校验模型指纹：不同 Embedding 模型的向量禁止混用，绝不静默降级
    model_guard.assert_compatible(collection)
    records = get_vector_store().list_records(collection)
    outcome.total_vectors = len(records)
    if not records:
        outcome.message = "知识库中没有可检索的文本块，请先上传并解析企业文档。"
        outcome.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return outcome

    query_tokens = tokenize_for_search(q)
    doc_tokens = [tokenize_for_search(r.text) for r in records]
    try:
        query_vec = np.asarray(get_embedder().encode([q])[0], dtype=np.float64)
        matrix = np.asarray([r.embedding for r in records], dtype=np.float64)
        vector_raw = _cosine_matrix(matrix, query_vec).tolist()
    except Exception as exc:
        # 维度/模型异常不再静默降级成关键词检索（那会让使用者误以为语义检索仍生效）
        raise VectorError(
            "向量检索计算失败，已停止检索",
            f"集合 {collection} 的向量与当前模型「{model_guard.current_fingerprint()['模型名称']}」"
            f"不兼容：{exc}。请执行 python scripts/rebuild_vectors.py 重建向量库。",
        ) from exc
    keyword_raw = _bm25(query_tokens, doc_tokens)

    vector_scores = _minmax([max(0.0, v) for v in vector_raw])
    keyword_scores = _minmax(keyword_raw)
    combined: list[float] = []
    for v, kw in zip(vector_scores, keyword_scores):
        if mode == "vector":
            combined.append(v)
        elif mode == "keyword":
            combined.append(kw)
        else:
            combined.append(w * v + (1 - w) * kw)

    # 无答案判定：使用「二元字组覆盖率」+「原始余弦相似度」，
    # 不能用 min-max 归一化后的分数（最高分恒为 1.0，无法反映绝对相关性）。
    # 只看「是否有任一二元字组命中」过于宽松：「公司 / 提供」等通用词会带偏判定，
    # 因此改为逐块计算查询二元字组的覆盖率并取最大值。
    query_bigrams = [token for token in query_tokens if len(token) >= 2]
    if query_bigrams:
        query_bigram_set = set(query_bigrams)
        best_hits = max(
            (len(query_bigram_set & {t for t in doc if len(t) >= 2}) for doc in doc_tokens),
            default=0,
        )
        best_coverage = best_hits / len(query_bigram_set)
    else:
        best_hits, best_coverage = 0, 1.0
    best_raw_vector = max((max(0.0, value) for value in vector_raw), default=0.0)
    if (
        best_hits < _NO_ANSWER_MIN_HITS
        and best_coverage < _NO_ANSWER_COVERAGE
        and best_raw_vector < _NO_ANSWER_SIMILARITY
    ):
        outcome.message = "知识库中没有检索到与该问题相关的资料，建议更换关键词或补充文档。"
        outcome.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return outcome

    order = sorted(range(len(records)), key=lambda i: -combined[i])[:k]
    hits: list[RetrievedChunk] = []
    for rank, idx in enumerate(order, start=1):
        record = records[idx]
        hits.append(
            RetrievedChunk(
                chunk_id=record.chunk_id,
                doc_id=record.doc_id,
                doc_name=record.doc_name,
                section=record.section,
                page=record.page,
                text=record.text,
                snippet=_snippet(record.text),
                score=round(combined[idx], 6),
                vector_score=round(max(0.0, vector_raw[idx]), 6),
                keyword_score=round(keyword_scores[idx], 6),
                rank=rank,
            )
        )
    outcome.message = f"共召回 {len(hits)} 个文本块。"

    if rerank:
        hits, applied, method = apply_rerank(q, hits, rerank_mode)
        outcome.rerank_applied = applied
        outcome.rerank_method = method
    outcome.hits = hits
    outcome.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return outcome
