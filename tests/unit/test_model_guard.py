"""模型指纹防混用：来源缺失/模型不一致必须显式报错，不得静默降级。"""
from __future__ import annotations

import pytest

from backend.core.errors import VectorError
from backend.database.db import get_conn
from backend.rag import model_guard
from backend.rag.embeddings import get_embedder
from backend.rag.retriever import search
from backend.rag.vectorstore import VectorRecord, get_vector_store
from backend.services import document_service

COLLECTION = "unit_model_guard"


def _seed() -> None:
    embedder = get_embedder()
    text = "员工申请年假需提前三个工作日提交申请，部门负责人两日内审批。"
    records = [
        VectorRecord(
            id=f"{COLLECTION}:c0", chunk_id="doc0-c0000", doc_id="doc0",
            doc_name="考勤制度.md", text=text, section="一、年假申请规定",
            page=None, embedding=embedder.encode([text])[0], collection=COLLECTION,
        )
    ]
    store = get_vector_store()
    store.delete_collection(COLLECTION)
    model_guard.clear_meta(COLLECTION)
    store.upsert(COLLECTION, records)
    model_guard.mark_written(COLLECTION, records, model_guard.current_fingerprint())


def test_compatible_collection_can_search():
    _seed()
    outcome = search("年假需要提前几天申请", collection=COLLECTION, top_k=2)
    assert outcome.hits


def test_missing_model_meta_blocks_search():
    _seed()
    model_guard.clear_meta(COLLECTION)
    with pytest.raises(VectorError) as exc:
        search("年假", collection=COLLECTION)
    assert "模型来源" in str(exc.value)


def test_mismatched_model_meta_blocks_search():
    _seed()
    with get_conn() as conn:
        conn.execute(
            "UPDATE embedding_meta SET model_key = ?, model_name = ? WHERE collection = ?",
            ("local:another-model:512", "另一个模型", COLLECTION),
        )
    with pytest.raises(VectorError) as exc:
        search("年假", collection=COLLECTION)
    assert "不一致" in str(exc.value)


def test_mark_written_rejects_wrong_dimension():
    _seed()
    fp = model_guard.current_fingerprint()
    bad = [
        VectorRecord(
            id="x", chunk_id="c", doc_id="d", doc_name="x.md", text="x",
            section=None, page=None, embedding=[0.1, 0.2], collection=COLLECTION,
        )
    ]
    with pytest.raises(VectorError) as exc:
        model_guard.mark_written(COLLECTION, bad, fp)
    assert "维度" in str(exc.value)


def test_reconcile_rebuilds_when_model_meta_is_stale(sample_markdown):
    """模型指纹不一致时，按原始文件重建，重建后可正常检索。"""
    data = sample_markdown.read_bytes()
    document_service.ingest_bytes(sample_markdown.name, data)
    with get_conn() as conn:
        conn.execute(
            "UPDATE embedding_meta SET model_key = ? WHERE collection = ?",
            ("local:old-model:512", "default"),
        )

    result = document_service.reconcile_vector_model("default")
    assert result["已重建"] is True
    assert result["重建文档数"] >= 1
    assert result["失败文档数"] == 0

    meta = model_guard.read_meta("default")
    assert meta["model_key"] == model_guard.current_fingerprint()["model_key"]
    assert search("年假天数", collection="default", top_k=3).hits
