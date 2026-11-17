"""单元测试：Embedding 接口、向量检索、混合检索、重排序、空结果处理。"""
from __future__ import annotations

import numpy as np
import pytest

from backend.rag import model_guard
from backend.rag.embeddings import HashEmbedder, get_embedder
from backend.rag.retriever import search
from backend.rag.vectorstore import VectorRecord, get_vector_store

COLLECTION = "unit_retrieval"


def _seed() -> None:
    embedder = get_embedder()
    rows = [
        ("考勤与请假制度.md", "一、年假申请规定", "员工申请年假需提前三个工作日提交申请，部门负责人两日内审批。"),
        ("费用报销制度.md", "二、报销时限", "差旅费用报销需在出差结束后五个工作日内提交报销单。"),
        ("IT服务规范.md", "三、软件安装", "设计类软件安装需部门负责人审批后由 IT 服务台统一处理。"),
    ]
    texts = [row[2] for row in rows]
    vectors = embedder.encode(texts)
    records = [
        VectorRecord(
            id=f"{COLLECTION}:c{i}", chunk_id=f"doc{i}-c0000", doc_id=f"doc{i}",
            doc_name=row[0], text=row[2], section=row[1], page=None,
            embedding=vectors[i], collection=COLLECTION,
        )
        for i, row in enumerate(rows)
    ]
    store = get_vector_store()
    store.delete_collection(COLLECTION)
    model_guard.clear_meta(COLLECTION)
    store.upsert(COLLECTION, records)
    # 与生产写入链路一致：登记本批向量由哪个 Embedding 模型生成
    model_guard.mark_written(COLLECTION, records, model_guard.current_fingerprint())


def test_hash_embedder_normalized():
    embedder = HashEmbedder()
    vector = np.asarray(embedder.encode(["年假申请规定"])[0])
    assert len(vector) == embedder.dim == 256
    assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-5


def test_similar_texts_have_higher_cosine():
    embedder = HashEmbedder()
    base = np.asarray(embedder.encode(["年假需要提前三个工作日申请"])[0])
    similar = np.asarray(embedder.encode(["年假提前三个工作日提交申请"])[0])
    unrelated = np.asarray(embedder.encode(["打印机卡纸故障处理方法"])[0])
    assert float(base @ similar) > float(base @ unrelated)


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_hybrid_modes_return_hits(mode):
    _seed()
    outcome = search("年假申请", collection=COLLECTION, top_k=2, mode=mode)
    assert len(outcome.hits) == 2
    assert outcome.hits[0].doc_name
    assert 0.0 <= outcome.hits[0].score <= 1.0
    assert outcome.total_vectors == 3


def test_search_result_contains_real_source():
    _seed()
    outcome = search("差旅报销", collection=COLLECTION, top_k=3, mode="hybrid")
    assert any("费用报销制度.md" == hit.doc_name for hit in outcome.hits)
    assert all(hit.section and hit.chunk_id and hit.snippet for hit in outcome.hits)


def test_rerank_records_original_rank():
    _seed()
    outcome = search("软件安装 设计类", collection=COLLECTION, top_k=3,
                     mode="hybrid", rerank=True, rerank_mode="rule")
    assert outcome.rerank_applied is True
    assert "规则式" in outcome.rerank_method
    assert all(hit.original_rank is not None for hit in outcome.hits)
    assert [hit.rank for hit in outcome.hits] == [1, 2, 3]


def test_empty_collection():
    outcome = search("任何问题", collection="empty_collection_xyz")
    assert outcome.hits == []
    assert "没有可检索" in outcome.message


def test_no_answer_query_returns_no_hits():
    _seed()
    outcome = search("公司是否提供免费住房补贴和购房贷款", collection=COLLECTION, top_k=3)
    assert outcome.hits == []
    assert "没有检索到" in outcome.message
