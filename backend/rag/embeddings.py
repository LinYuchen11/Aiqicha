"""双档 Embedding：离线词面哈希向量（备用） + 本地 BGE 语义向量（正式演示推荐）。

重要：hash 档是「字符 n-gram → 哈希分桶」的词面统计向量，只能匹配字面重合，
**不是语义 Embedding**；它只用于零下载、零费用的离线备用与链路演示。
正式演示推荐 EMBEDDING_MODE=local（BAAI/bge-small-zh-v1.5）。
不同模型生成的向量语义空间不同，禁止混用；模型指纹由 model_guard 校验。
"""
from __future__ import annotations

import hashlib
import threading
from typing import Protocol

import numpy as np

from backend.core.config import settings
from backend.core.errors import ConfigError
from backend.core.log_utils import get_logger
from backend.rag.cleaner import tokenize_for_search

logger = get_logger(__name__)
_DIM = 256
RECOMMENDED_MODE = "local"


class BaseEmbedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """离线词面哈希向量：纯 Python + numpy，无语义、无需下载任何模型。"""

    name = "内置词面哈希向量（离线备用，非语义 Embedding）"
    dim = _DIM

    def encode_one(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in tokenize_for_search(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
            vec[int.from_bytes(digest, "little") % self.dim] += 1.0
        vec = np.log1p(vec)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self.encode_one(t) for t in texts]


class LocalEmbedder:
    """正式演示推荐：本地 sentence-transformers / BGE 语义向量。"""

    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ConfigError(
                "未安装本地语义向量依赖",
                "请执行 python -m pip install -i https://pypi.org/simple "
                "-r requirements-optional.txt 后重试",
            ) from exc
        try:
            self.model = SentenceTransformer(model_name)
        except Exception as exc:
            raise ConfigError("本地语义向量模型加载失败", str(exc)) from exc
        self.model_name = model_name
        self.name = f"本地 BGE 语义向量（{model_name}）"
        self.dim = int(self.model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True, batch_size=16)
        return [v.tolist() for v in vectors]


_lock = threading.Lock()
_embedder: BaseEmbedder | None = None
_effective_mode: str = ""
_degrade_reason: str = ""


def get_embedder() -> BaseEmbedder:
    """返回当前实际生效的 Embedder；local 任意环节失败都降级并记录原因。"""
    global _embedder, _effective_mode, _degrade_reason
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        if settings.embedding_mode == "local":
            try:
                _embedder = LocalEmbedder(settings.embedding_model)
                _effective_mode = "local"
                _degrade_reason = ""
            except Exception as exc:  # 依赖缺失、下载失败、加载失败一律降级
                _degrade_reason = getattr(exc, "message", None) or str(exc)
                logger.warning("本地语义向量不可用，已降级为离线词面哈希向量：%s", _degrade_reason)
                _embedder = HashEmbedder()
                _effective_mode = "hash（local 降级）"
        else:
            _embedder = HashEmbedder()
            _effective_mode = "hash"
            _degrade_reason = ""
    return _embedder


def reset_embedder() -> None:
    """切换档位后清空进程级单例，让下一次调用重新加载（供切换脚本使用）。"""
    global _embedder, _effective_mode, _degrade_reason
    with _lock:
        _embedder = None
        _effective_mode = ""
        _degrade_reason = ""


def embedding_info() -> dict:
    embedder = get_embedder()
    semantic = _effective_mode.startswith("local")
    return {
        "配置档位": settings.embedding_mode,
        "实际档位": _effective_mode,
        "模型名称": embedder.name,
        "向量维度": embedder.dim,
        "需要下载模型": semantic,
        "是否语义向量": semantic,
        "正式演示推荐档位": RECOMMENDED_MODE,
        "推荐模型": settings.embedding_model,
        "降级原因": _degrade_reason or "无",
        "说明": (
            "当前为本地 BGE 语义向量，可用于正式演示与语义检索效果对照。"
            if semantic else
            "当前为词面哈希向量，仅匹配字面重合，不是语义 Embedding；仅作离线备用。"
        ),
    }


def embedding_fingerprint() -> dict:
    """模型指纹：写入向量库与检索前校验，禁止不同模型向量混用。"""
    embedder = get_embedder()
    semantic = _effective_mode.startswith("local")
    if semantic:
        key = f"local:{settings.embedding_model}:{embedder.dim}"
    else:
        key = f"hash:{embedder.dim}"
    return {
        "model_key": key,
        "模型名称": embedder.name,
        "向量维度": embedder.dim,
        "实际档位": _effective_mode,
        "配置档位": settings.embedding_mode,
        "是否语义向量": semantic,
        "降级原因": _degrade_reason,
    }
