"""文档业务服务：上传校验 → 解析 → 清洗分块 → Embedding → 向量持久化 → 状态更新。

支持多文件、重复识别、空文件/解析失败提示、重新处理、级联删除、检索测试。
评估实验使用独立 collection，不会污染生产知识库。
"""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from backend.core.config import SUPPORTED_EXTENSIONS, settings
from backend.core.errors import DuplicateError, FileError, NotFoundError, ParseError
from backend.core.log_utils import get_logger
from backend.database import document_repo
from backend.rag.chunker import split_into_chunks
from backend.rag import model_guard
from backend.rag.embeddings import embedding_info, get_embedder
from backend.rag.parsers import parse_file
from backend.rag.retriever import search
from backend.rag.vectorstore import VectorRecord, get_vector_store

logger = get_logger(__name__)
DEFAULT_COLLECTION = "default"


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.\-]", "_", Path(name).name)
    return cleaned[:120] or "upload.txt"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_doc_id(filename: str) -> str:
    return "sample-" + hashlib.md5(filename.encode("utf-8")).hexdigest()[:8]


def _embed_and_store(chunks, filename: str, doc_id: str, collection: str) -> int:
    if not chunks:
        return 0
    vectors = get_embedder().encode([chunk.text for chunk in chunks])
    records = [
        VectorRecord(
            id=f"{collection}:{chunk.id}", chunk_id=chunk.id, doc_id=doc_id,
            doc_name=filename, text=chunk.text, section=chunk.section,
            page=chunk.page, embedding=vector, collection=collection,
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    store = get_vector_store()
    store.delete_doc(collection, doc_id)
    written = store.upsert(collection, records)
    # 登记「本批向量由哪个模型生成」，供检索前一致性校验
    model_guard.mark_written(collection, records, model_guard.current_fingerprint())
    return written


def ingest_bytes(
    filename: str,
    data: bytes,
    is_sample: bool = False,
    source_path: str | None = None,
    collection: str = DEFAULT_COLLECTION,
    chunk_size: int | None = None,
    overlap: int | None = None,
    strategy: str = "semantic",
) -> dict:
    """单个文档完整处理链路。失败时把状态与中文错误写回文档表。"""
    safe_name = _safe_filename(filename)
    ext = Path(safe_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FileError(
            f"不支持的文件类型：{ext or '无扩展名'}",
            "仅支持 PDF、DOCX、TXT、MD 四种格式",
        )
    if not data:
        raise FileError("文件内容为空", f"文件 {safe_name} 没有可读取的内容")
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise FileError(
            f"文件超过大小限制（{settings.max_file_size_mb} MB）",
            f"文件 {safe_name} 大小为 {len(data) / 1024 / 1024:.2f} MB",
        )

    digest = _sha256(data)
    doc_id = _stable_doc_id(safe_name) if is_sample else uuid.uuid4().hex[:12]
    if collection == DEFAULT_COLLECTION and document_repo.find_by_sha(digest):
        raise DuplicateError(f"重复文件：{safe_name}", "知识库中已存在内容完全相同的文档，无需重复上传")

    if source_path:
        stored_path = str(source_path)
    else:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        stored_path = str(settings.upload_dir / f"{doc_id}_{safe_name}")
        Path(stored_path).write_bytes(data)

    if collection == DEFAULT_COLLECTION:
        document_repo.insert_document(
            doc_id, safe_name, ext, len(data), digest, stored_path, int(is_sample)
        )
        document_repo.update_document(doc_id, status="解析中")

    try:
        parsed = parse_file(Path(stored_path), safe_name)
        chunks = split_into_chunks(
            parsed.blocks, doc_id,
            chunk_size or settings.chunk_size,
            settings.chunk_overlap if overlap is None else overlap,
            strategy,
        )
        if not chunks:
            raise ParseError("文本分块结果为空", "文档内容过短或均为空白字符")
        if collection == DEFAULT_COLLECTION:
            document_repo.replace_chunks(doc_id, chunks)
            document_repo.update_document(doc_id, status="向量化中")
        count = _embed_and_store(chunks, safe_name, doc_id, collection)
        if collection == DEFAULT_COLLECTION:
            document_repo.update_document(
                doc_id, status="已完成", chunk_count=len(chunks), error_msg=None
            )
        return {
            "文件名称": safe_name,
            "文档编号": doc_id,
            "状态": "已完成",
            "文本块数": len(chunks),
            "向量数": count,
            "解析方式": parsed.parser,
            "分块参数": {
                "块大小": chunk_size or settings.chunk_size,
                "重叠": settings.chunk_overlap if overlap is None else overlap,
                "策略": strategy,
            },
            "提示": "文档已完成解析、分块与向量化。",
        }
    except Exception as exc:
        message = exc.message if hasattr(exc, "message") else str(exc)
        if collection == DEFAULT_COLLECTION:
            document_repo.update_document(doc_id, status="失败", chunk_count=0, error_msg=message)
        logger.warning("文档处理失败 %s：%s", safe_name, message)
        raise


def process_uploads(files: list[tuple[str, bytes]]) -> dict:
    """多文件上传：单个失败不影响其它文件，逐条返回中文结果。"""
    results = []
    for filename, data in files:
        try:
            results.append({"成功": True, **ingest_bytes(filename, data)})
        except Exception as exc:
            results.append({
                "成功": False,
                "文件名称": _safe_filename(filename),
                "状态": "失败",
                "错误类型": getattr(exc, "code", "文件处理失败"),
                "错误说明": getattr(exc, "message", str(exc)),
                "详细说明": getattr(exc, "detail", ""),
            })
    return {
        "结果": results,
        "成功数": sum(1 for item in results if item["成功"]),
        "失败数": sum(1 for item in results if not item["成功"]),
    }


def reconcile_vector_model(collection: str = DEFAULT_COLLECTION) -> dict:
    """更换 Embedding 模型后自动按原始文件重建向量，绝不混用不同模型的向量。

    旧实现按内容 SHA 短路跳过重建，且向量维度不匹配时被 retriever 静默降级为
    关键词检索；这里改为先比对模型指纹，不一致就清空集合并逐文档重新向量化。
    """
    fp = model_guard.current_fingerprint()
    meta = model_guard.read_meta(collection)
    count = get_vector_store().count(collection)
    if count == 0:
        if meta:
            model_guard.clear_meta(collection)
        return {"已重建": False, "原因": "集合为空", "模型": fp["模型名称"]}
    if meta and meta["model_key"] == fp["model_key"]:
        return {"已重建": False, "原因": "模型指纹一致", "模型": fp["模型名称"]}

    reason = "来源标记缺失" if not meta else f"模型切换：{meta['model_name']} → {fp['模型名称']}"
    get_vector_store().delete_collection(collection)
    model_guard.clear_meta(collection)
    rebuilt, failed = 0, []
    for doc in document_repo.list_documents():
        try:
            reprocess_document(doc["id"])
            rebuilt += 1
        except Exception as exc:
            message = getattr(exc, "message", None) or str(exc)
            failed.append(f"{doc['filename']}：{message}")
            document_repo.update_document(doc["id"], status="失败", error_msg=message)
    if failed:
        logger.warning("向量库重建部分失败：%s", failed)
    return {
        "已重建": True, "原因": reason, "模型": fp["模型名称"],
        "重建文档数": rebuilt, "失败文档数": len(failed), "失败明细": failed,
        "提示": "不同 Embedding 模型产生的向量禁止混用，已按原始文件重建该集合。",
    }


def ensure_sample_documents() -> dict:
    """幂等同步预置模拟企业文档，保证开箱即用。

    先做模型指纹一致性检查（必要时强制重建向量库），再以「文件名 + 内容指纹」
    为准同步文档：内容未变化则跳过；磁盘上被修改过的文档原地重建（同一 doc_id）。
    """
    rebuild = reconcile_vector_model()
    files = sorted(settings.sample_dir.glob("*.md"))
    existing = {
        item["filename"]: item
        for item in document_repo.list_documents()
        if item["is_sample"]
    }
    imported = 0
    updated = 0
    for path in files:
        name = _safe_filename(path.name)
        data = path.read_bytes()
        digest = _sha256(data)
        doc = existing.get(name)
        if doc and doc["sha256"] == digest:
            continue
        try:
            if doc:
                reprocess_document(doc["id"], source_path=str(path))
                updated += 1
            else:
                ingest_bytes(path.name, data, is_sample=True, source_path=str(path))
                imported += 1
        except Exception as exc:
            logger.warning("模拟文档同步失败 %s：%s", path.name, exc)
    return {
        "已导入": imported,
        "已更新": updated,
        "已存在": len(files) - imported - updated,
        "文档总数": len(files),
        "向量库重建": rebuild,
    }


def reprocess_document(
    doc_id: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
    source_path: str | None = None,
) -> dict:
    """按原始文件重新解析、分块、向量化，并同步内容指纹。"""
    doc = document_repo.get_document(doc_id)
    if not doc:
        raise NotFoundError("文档不存在", f"未找到编号 {doc_id} 的文档")
    path = Path(source_path or doc.get("source_path") or "")
    if not path.exists():
        raise FileError("原始文件已丢失，无法重新处理", str(path))
    data = path.read_bytes()
    digest = _sha256(data)
    other = document_repo.find_by_sha(digest)
    if other and other["id"] != doc_id:
        raise DuplicateError(
            "文档内容与其它文档完全重复",
            f"与《{other['filename']}》内容相同，请先删除其中一份再重新处理",
        )
    parsed = parse_file(path, doc["filename"])
    chunks = split_into_chunks(
        parsed.blocks, doc_id,
        chunk_size or settings.chunk_size,
        settings.chunk_overlap if overlap is None else overlap,
    )
    document_repo.replace_chunks(doc_id, chunks)
    count = _embed_and_store(chunks, doc["filename"], doc_id, DEFAULT_COLLECTION)
    document_repo.update_document(
        doc_id, status="已完成", chunk_count=len(chunks), error_msg=None,
        sha256=digest, source_path=str(path),
    )
    return {
        "文档编号": doc_id, "文件名称": doc["filename"], "状态": "已完成",
        "文本块数": len(chunks), "向量数": count,
        "提示": "文档已重新解析并重建向量数据。",
    }


def delete_document(doc_id: str) -> dict:
    doc = document_repo.get_document(doc_id)
    if not doc:
        raise NotFoundError("文档不存在", f"未找到编号 {doc_id} 的文档")
    removed_vectors = get_vector_store().delete_doc(DEFAULT_COLLECTION, doc_id)
    document_repo.delete_document(doc_id)
    path = Path(doc.get("source_path") or "")
    if path.exists() and settings.upload_dir in path.parents:
        try:
            path.unlink()
        except OSError:
            pass
    return {
        "文档编号": doc_id, "文件名称": doc["filename"],
        "已删除向量数": removed_vectors,
        "提示": "文档、文本块与对应向量数据已全部删除。",
    }


def document_detail(doc_id: str) -> dict:
    doc = document_repo.get_document(doc_id)
    if not doc:
        raise NotFoundError("文档不存在", f"未找到编号 {doc_id} 的文档")
    return {"文档": doc, "文本块": document_repo.list_chunks(doc_id)}


def overview() -> dict:
    store = get_vector_store()
    return {
        "文档": document_repo.list_documents(),
        "统计": document_repo.stats(),
        "向量模型": embedding_info(),
        "向量数量": store.count(DEFAULT_COLLECTION),
        "向量库": store.name,
        "支持格式": sorted(SUPPORTED_EXTENSIONS),
        "大小限制MB": settings.max_file_size_mb,
    }


def retrieval_test(query: str, top_k: int, mode: str, hybrid_weight: float, rerank: bool) -> dict:
    outcome = search(
        query=query, collection=DEFAULT_COLLECTION, top_k=top_k, mode=mode,
        hybrid_weight=hybrid_weight, rerank=rerank,
    )
    return {
        "query": outcome.query, "mode": outcome.mode, "top_k": outcome.top_k,
        "hybrid_weight": outcome.hybrid_weight, "rerank_applied": outcome.rerank_applied,
        "rerank_method": outcome.rerank_method, "total_vectors": outcome.total_vectors,
        "results": [item.model_dump() for item in outcome.hits],
        "elapsed_ms": outcome.elapsed_ms, "message": outcome.message,
    }


def build_experiment_collection(
    collection: str, chunk_size: int, overlap: int, strategy: str = "semantic"
) -> dict:
    """为评估实验重建独立向量集合，不改动生产知识库与文档表。"""
    files = sorted(settings.sample_dir.glob("*.md"))
    if not files:
        raise FileError("没有可用的模拟企业文档", "请先在 data/sample_docs 下准备文档")
    store = get_vector_store()
    store.delete_collection(collection)
    model_guard.clear_meta(collection)
    total = 0
    for path in files:
        parsed = parse_file(path, path.name)
        doc_id = _stable_doc_id(path.name)
        chunks = split_into_chunks(parsed.blocks, doc_id, chunk_size, overlap, strategy)
        total += _embed_and_store(chunks, path.name, doc_id, collection)
    return {
        "集合": collection, "文档数": len(files), "文本块数": total,
        "块大小": chunk_size, "重叠": overlap, "分块策略": strategy,
    }
