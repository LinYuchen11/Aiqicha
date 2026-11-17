"""重排序：默认关闭；rule 为确定性规则式；local 为真实 CrossEncoder 模型。

规则式重排不是模型；模型不可用时必须显式标注「已降级」，绝不能把降级结果
描述成模型重排效果。local 分支一次批量 predict，避免逐条前向的开销。
"""
from __future__ import annotations

import importlib.util

from backend.core.config import settings
from backend.core.errors import ConfigError
from backend.core.log_utils import get_logger
from backend.models.schemas import RetrievedChunk
from backend.rag.cleaner import keyword_overlap, tokenize_for_search

logger = get_logger(__name__)
CROSS_ENCODER_MODEL = "BAAI/bge-reranker-base"
_cross_encoder = None
_cross_encoder_error = ""


def _rule_score(query: str, hit: RetrievedChunk) -> float:
    overlap = keyword_overlap(query, hit.text)
    query_tokens = set(tokenize_for_search(query))
    section_bonus = 0.0
    if hit.section and any(token in hit.section for token in query_tokens):
        section_bonus = 0.08
    length_penalty = 0.02 if len(hit.text) < 60 else 0.0
    return 0.55 * hit.score + 0.35 * overlap + section_bonus - length_penalty


def _get_cross_encoder():
    global _cross_encoder, _cross_encoder_error
    if _cross_encoder is not None:
        return _cross_encoder
    if _cross_encoder_error:
        raise ConfigError("本地重排模型不可用", _cross_encoder_error)
    try:
        from sentence_transformers import CrossEncoder
        _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
    except Exception as exc:
        _cross_encoder_error = str(exc)
        raise ConfigError("本地重排模型加载失败", _cross_encoder_error) from exc
    return _cross_encoder


def cross_encoder_status() -> dict:
    """供评估实验判断能否真实运行模型重排；依赖缺失时直接判定不可用，不触发下载。"""
    if importlib.util.find_spec("sentence_transformers") is None:
        return {
            "可用": False, "模型": CROSS_ENCODER_MODEL,
            "原因": "未安装 sentence-transformers（可选依赖），模型重排实验未运行",
        }
    try:
        _get_cross_encoder()
        return {"可用": True, "模型": CROSS_ENCODER_MODEL, "原因": ""}
    except ConfigError as exc:
        return {"可用": False, "模型": CROSS_ENCODER_MODEL, "原因": exc.message}


def apply_rerank(
    query: str, hits: list[RetrievedChunk], mode: str | None = None
) -> tuple[list[RetrievedChunk], bool, str]:
    """返回 (重排结果, 是否实际应用, 使用的方法名)。方法名会如实标注降级。"""
    active = (mode or settings.rerank_mode or "none").lower()
    if active == "none" or not hits:
        return hits, False, "未启用"

    if active not in {"rule", "local"}:
        logger.warning("未知重排模式 %s，已显式降级为规则式", active)
        active = "rule"
        method = "规则式重排序（未知模式降级，非模型）"
    elif active == "local":
        method = "CrossEncoder 模型重排序"
    else:
        method = "规则式重排序（非模型）"

    for hit in hits:
        hit.original_rank = hit.rank

    if active == "local":
        try:
            model = _get_cross_encoder()
            # 一次批量前向，避免 N 个候选跑 N 次模型
            raw_scores = model.predict([(query, hit.text) for hit in hits], batch_size=16)
            scores = [float(value) for value in raw_scores]
        except ConfigError as exc:
            logger.warning("CrossEncoder 不可用，已显式降级为规则式：%s", exc.message)
            method = "规则式重排序（CrossEncoder 不可用降级，非模型）"
            scores = [_rule_score(query, hit) for hit in hits]
    else:
        scores = [_rule_score(query, hit) for hit in hits]

    scored = sorted(zip(scores, hits), key=lambda item: -item[0])
    for score, hit in scored:
        hit.rerank_score = round(float(score), 6)
    ordered = [hit for _, hit in scored]
    for index, hit in enumerate(ordered, start=1):
        hit.rank = index
    return ordered, True, method
