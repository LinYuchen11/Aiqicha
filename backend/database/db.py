"""SQLite 连接管理。统一走 get_conn()，保证事务、外键与异常回滚。"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

from backend.core.config import settings
from backend.core.errors import DBError
from backend.database.schema import SCHEMA_SQL, SEED_IT_SERVICES

_init_lock = threading.Lock()
_initialized = False


def now_iso() -> str:
    """本地时间 ISO 字符串，用于所有业务表的时间字段。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def init_database() -> None:
    """建表 + 初始化预置模拟数据。可重复调用（幂等）。"""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        settings.vector_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(settings.db_path), timeout=30)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                "INSERT OR IGNORE INTO it_services "
                "(service_key, category, name, description, supported, apply_channel, sla) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                SEED_IT_SERVICES,
            )
            # 轻量迁移：兼容早期已创建的数据库，补齐评估明细的方案列
            columns = {row[1] for row in conn.execute("PRAGMA table_info(eval_items)")}
            if "scheme" not in columns:
                conn.execute("ALTER TABLE eval_items ADD COLUMN scheme TEXT NOT NULL DEFAULT '默认'")
            if "context_support" not in columns:
                conn.execute("ALTER TABLE eval_items ADD COLUMN context_support REAL")
            conn.commit()
        except sqlite3.Error as exc:
            raise DBError("数据库初始化失败", str(exc)) from exc
        finally:
            conn.close()
        _initialized = True


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    init_database()
    conn = sqlite3.connect(str(settings.db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise DBError("数据库读写失败", str(exc)) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql: str, params: Sequence[Any] = ()) -> list[dict]:
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def fetch_one(sql: str, params: Sequence[Any] = ()) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    with get_conn() as conn:
        cursor = conn.execute(sql, params)
        return cursor.lastrowid or 0


def executemany(sql: str, rows: Sequence[Sequence[Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(sql, rows)
