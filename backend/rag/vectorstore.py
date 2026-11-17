"""持久化向量库：默认 SQLite 向量表，可选 Chroma。两者接口完全一致。"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from backend.core.config import settings
from backend.core.errors import ConfigError, VectorError
from backend.core.log_utils import get_logger
from backend.database.db import fetch_all, fetch_one, get_conn

logger = get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class VectorRecord:
    id: str
    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    section: str | None
    page: int | None
    embedding: list[float]
    collection: str = "default"


class BaseVectorStore(Protocol):
    name: str

    def upsert(self, collection: str, records: list[VectorRecord]) -> int: ...
    def delete_doc(self, collection: str, doc_id: str) -> int: ...
    def delete_collection(self, collection: str) -> int: ...
    def list_records(self, collection: str) -> list[VectorRecord]: ...
    def count(self, collection: str | None = None) -> int: ...


class SqliteVectorStore:
    """向量以 JSON 数组存 SQLite，检索时载入内存计算余弦相似度，重启后数据仍在。"""

    name = "SQLite 持久化向量表"

    def upsert(self, collection: str, records: list[VectorRecord]) -> int:
        if not records:
            return 0
        rows = [
            (
                f"{collection}:{r.chunk_id}", collection, r.chunk_id, r.doc_id,
                r.text, r.doc_name, r.section, r.page,
                json.dumps(r.embedding, ensure_ascii=False), _now(),
            )
            for r in records
        ]
        try:
            with get_conn() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO vectors "
                    "(id, collection, chunk_id, doc_id, text, doc_name, section, page, embedding, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
        except Exception as exc:
            raise VectorError("向量写入失败", str(exc)) from exc
        return len(rows)

    def delete_doc(self, collection: str, doc_id: str) -> int:
        with get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM vectors WHERE collection = ? AND doc_id = ?", (collection, doc_id)
            )
            return cursor.rowcount or 0

    def delete_collection(self, collection: str) -> int:
        with get_conn() as conn:
            cursor = conn.execute("DELETE FROM vectors WHERE collection = ?", (collection,))
            return cursor.rowcount or 0

    def list_records(self, collection: str) -> list[VectorRecord]:
        rows = fetch_all("SELECT * FROM vectors WHERE collection = ?", (collection,))
        records: list[VectorRecord] = []
        for row in rows:
            try:
                embedding = json.loads(row["embedding"])
            except (ValueError, TypeError):
                continue
            records.append(
                VectorRecord(
                    id=row["id"], chunk_id=row["chunk_id"], doc_id=row["doc_id"],
                    doc_name=row["doc_name"], text=row["text"], section=row["section"],
                    page=row["page"], embedding=embedding, collection=row["collection"],
                )
            )
        return records

    def count(self, collection: str | None = None) -> int:
        if collection:
            row = fetch_one("SELECT COUNT(*) AS n FROM vectors WHERE collection = ?", (collection,))
        else:
            row = fetch_one("SELECT COUNT(*) AS n FROM vectors")
        return int(row["n"]) if row else 0


class ChromaVectorStore:
    """可选实现：Chroma 持久化。集合名做安全化处理，避免非法字符。"""

    def __init__(self) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise ConfigError(
                "未安装 Chroma 依赖",
                "请执行 python -m pip install -r requirements-optional.txt，或设置 VECTOR_STORE=sqlite",
            ) from exc
        settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
        self.name = "Chroma 持久化向量库"

    @staticmethod
    def _safe(name: str) -> str:
        return "eka_" + re.sub(r"[^a-zA-Z0-9_-]", "_", name)

    def _col(self, collection: str):
        return self.client.get_or_create_collection(self._safe(collection))

    def upsert(self, collection: str, records: list[VectorRecord]) -> int:
        if not records:
            return 0
        col = self._col(collection)
        col.upsert(
            ids=[f"{collection}:{r.chunk_id}" for r in records],
            embeddings=[r.embedding for r in records],
            documents=[r.text for r in records],
            metadatas=[
                {
                    "chunk_id": r.chunk_id, "doc_id": r.doc_id, "doc_name": r.doc_name,
                    "section": r.section or "", "page": r.page or 0,
                }
                for r in records
            ],
        )
        return len(records)

    def delete_doc(self, collection: str, doc_id: str) -> int:
        col = self._col(collection)
        before = col.count()
        col.delete(where={"doc_id": doc_id})
        return max(0, before - col.count())

    def delete_collection(self, collection: str) -> int:
        try:
            col = self._col(collection)
            n = col.count()
            self.client.delete_collection(self._safe(collection))
            return n
        except Exception:
            return 0

    def list_records(self, collection: str) -> list[VectorRecord]:
        col = self._col(collection)
        data = col.get(include=["embeddings", "documents", "metadatas"])
        records: list[VectorRecord] = []
        ids = data.get("ids") or []
        for i, rid in enumerate(ids):
            meta = (data.get("metadatas") or [{}])[i] or {}
            emb = (data.get("embeddings") or [[]])[i]
            records.append(
                VectorRecord(
                    id=rid, chunk_id=str(meta.get("chunk_id", rid)),
                    doc_id=str(meta.get("doc_id", "")), doc_name=str(meta.get("doc_name", "")),
                    text=(data.get("documents") or [""])[i] or "",
                    section=meta.get("section") or None,
                    page=meta.get("page") or None,
                    embedding=[float(x) for x in emb], collection=collection,
                )
            )
        return records

    def count(self, collection: str | None = None) -> int:
        if collection:
            return self._col(collection).count()
        return sum(self._col(c.name).count() for c in self.client.list_collections())


_lock = threading.Lock()
_store: BaseVectorStore | None = None


def get_vector_store() -> BaseVectorStore:
    global _store
    if _store is not None:
        return _store
    with _lock:
        if _store is not None:
            return _store
        if settings.vector_store == "chroma":
            try:
                _store = ChromaVectorStore()
            except ConfigError as exc:
                logger.warning("Chroma 不可用，已降级为 SQLite 向量表：%s", exc.message)
                _store = SqliteVectorStore()
        else:
            _store = SqliteVectorStore()
    return _store
