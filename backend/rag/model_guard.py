"""Embedding 模型指纹与向量库一致性保护。

不同模型（词面哈希 / BGE）产生的向量维度与语义空间都不同，混用会让余弦
相似度失去意义，而且旧实现会静默降级成纯关键词检索、让使用者误以为语义
检索仍在生效。本模块为每个 collection 记录来源模型，并在检索 / 写入时校验。
"""
from __future__ import annotations

from backend.core.errors import VectorError
from backend.database.db import fetch_one, get_conn, now_iso
from backend.rag.embeddings import embedding_fingerprint
from backend.rag.vectorstore import VectorRecord, get_vector_store


def current_fingerprint() -> dict:
    return embedding_fingerprint()


def read_meta(collection: str) -> dict | None:
    row = fetch_one("SELECT * FROM embedding_meta WHERE collection = ?", (collection,))
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def clear_meta(collection: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM embedding_meta WHERE collection = ?", (collection,))


def mark_written(collection: str, records: list[VectorRecord], fp: dict) -> None:
    """写入向量后登记模型来源，并校验本批向量维度一致。"""
    if not records:
        return
    bad = sum(1 for item in records if len(item.embedding) != fp["向量维度"])
    if bad:
        raise VectorError(
            "向量维度与当前模型不一致",
            f"本次写入有 {bad} 条向量维度不等于 {fp['向量维度']}，已拒绝混用，请重建向量库。",
        )
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO embedding_meta "
            "(collection, model_key, model_name, dim, effective_mode, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                collection, fp["model_key"], fp["模型名称"], fp["向量维度"],
                fp["实际档位"], now_iso(),
            ),
        )


def assert_compatible(collection: str) -> dict:
    """检索前校验；来源不明或模型不一致时直接报中文错误，绝不静默混用。"""
    fp = current_fingerprint()
    count = get_vector_store().count(collection)
    if count == 0:
        return fp
    meta = read_meta(collection)
    if not meta:
        raise VectorError(
            "向量库缺少模型来源标记",
            f"集合 {collection} 中有 {count} 条向量，但没有记录生成它的 Embedding 模型。"
            "无法确认能否与当前模型混用，请执行 python scripts/rebuild_vectors.py 重建向量库。",
        )
    if meta["model_key"] != fp["model_key"]:
        raise VectorError(
            "Embedding 模型与向量库不一致",
            f"集合 {collection} 由「{meta['model_name']}」（{meta['dim']} 维）生成，"
            f"当前模型是「{fp['模型名称']}」（{fp['向量维度']} 维）。"
            "不同模型的向量禁止混用，请执行 python scripts/rebuild_vectors.py 重建，"
            "或把 EMBEDDING_MODE 改回原档位。",
        )
    return fp


def compatibility_status(collection: str) -> dict:
    """给健康接口 / 前端用的只读状态，不抛异常。"""
    fp = current_fingerprint()
    meta = read_meta(collection)
    count = get_vector_store().count(collection)
    consistent = (count == 0) or (meta is not None and meta["model_key"] == fp["model_key"])
    return {
        "集合": collection,
        "向量数": count,
        "当前模型": fp["模型名称"],
        "库内模型": meta["model_name"] if meta else "未登记",
        "是否一致": consistent,
        "提示": "一致" if consistent else "模型来源不一致或缺失，需要重建向量库",
    }
