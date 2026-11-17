"""文档元数据与文本块仓储。"""
from __future__ import annotations

from typing import Iterable

from backend.database.db import fetch_all, fetch_one, get_conn, now_iso
from backend.rag.chunker import Chunk

# sha256 允许更新：重新处理文档后必须同步内容指纹，否则重启时会误判为「新文档」
_UPDATABLE = {"status", "chunk_count", "error_msg", "source_path", "sha256", "updated_at"}


def insert_document(
    doc_id: str, filename: str, file_type: str, size_bytes: int,
    sha256: str, source_path: str, is_sample: int = 0,
) -> None:
    now = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO documents "
            "(id, filename, file_type, size_bytes, sha256, status, chunk_count, error_msg, "
            " source_path, is_sample, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '待处理', 0, NULL, ?, ?, ?, ?)",
            (doc_id, filename, file_type, size_bytes, sha256, source_path, is_sample, now, now),
        )


def find_by_sha(sha256: str) -> dict | None:
    return fetch_one("SELECT * FROM documents WHERE sha256 = ?", (sha256,))


def get_document(doc_id: str) -> dict | None:
    return fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))


def list_documents() -> list[dict]:
    return fetch_all("SELECT * FROM documents ORDER BY created_at DESC, id DESC")


def update_document(doc_id: str, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not allowed:
        return
    allowed["updated_at"] = now_iso()
    columns = ", ".join(f"{k} = ?" for k in allowed)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE documents SET {columns} WHERE id = ?",
            (*allowed.values(), doc_id),
        )


def delete_document(doc_id: str) -> bool:
    """级联删除元数据与文本块；向量数据由文档服务单独清理。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return (cursor.rowcount or 0) > 0


def replace_chunks(doc_id: str, chunks: Iterable[Chunk]) -> int:
    rows = [
        (
            c.id, c.doc_id, c.chunk_index, c.text, c.section, c.page,
            c.char_start, c.char_end, now_iso(),
        )
        for c in chunks
    ]
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        if rows:
            conn.executemany(
                "INSERT INTO chunks "
                "(id, doc_id, chunk_index, text, section, page, char_start, char_end, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    return len(rows)


def list_chunks(doc_id: str) -> list[dict]:
    return fetch_all("SELECT * FROM chunks WHERE doc_id = ? ORDER BY chunk_index", (doc_id,))


def get_chunk(chunk_id: str) -> dict | None:
    return fetch_one("SELECT * FROM chunks WHERE id = ?", (chunk_id,))


def stats() -> dict:
    docs = list_documents()
    total_chunks = fetch_one("SELECT COUNT(*) AS n FROM chunks")
    return {
        "文档总数": len(docs),
        "处理成功": sum(1 for d in docs if d["status"] == "已完成"),
        "处理中": sum(1 for d in docs if d["status"] in ("待处理", "解析中", "向量化中")),
        "处理失败": sum(1 for d in docs if d["status"] == "失败"),
        "文本块总数": int(total_chunks["n"]) if total_chunks else 0,
        "占用字节": sum(int(d["size_bytes"]) for d in docs),
    }
