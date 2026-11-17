"""会话与消息仓储：所有读写按 session_id 隔离，历史对话持久化。"""
from __future__ import annotations

import json
import uuid

from backend.database.db import fetch_all, fetch_one, get_conn, now_iso


def create_session(session_id: str | None = None, title: str = "新对话") -> dict:
    sid = session_id or uuid.uuid4().hex
    now = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO conversations "
            "(session_id, title, created_at, updated_at, pending_ticket, pending_intent) "
            "VALUES (?, ?, ?, ?, NULL, NULL)",
            (sid, title, now, now),
        )
    return get_session(sid) or {"session_id": sid, "title": title}


def ensure_session(session_id: str | None) -> dict:
    if session_id:
        existing = get_session(session_id)
        if existing:
            return existing
        return create_session(session_id)
    return create_session()


def get_session(session_id: str) -> dict | None:
    return fetch_one("SELECT * FROM conversations WHERE session_id = ?", (session_id,))


def list_sessions(limit: int = 50) -> list[dict]:
    rows = fetch_all(
        "SELECT c.session_id, c.title, c.created_at, c.updated_at, "
        "(SELECT COUNT(*) FROM messages m WHERE m.session_id = c.session_id) AS message_count "
        "FROM conversations c ORDER BY c.updated_at DESC LIMIT ?",
        (limit,),
    )
    return rows


def touch_session(session_id: str, title: str | None = None) -> None:
    if title:
        with get_conn() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ?, title = ? WHERE session_id = ?",
                (now_iso(), title[:60], session_id),
            )
    else:
        with get_conn() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE session_id = ?",
                (now_iso(), session_id),
            )


def set_pending(session_id: str, draft: dict | None, intent: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET pending_ticket = ?, pending_intent = ?, updated_at = ? "
            "WHERE session_id = ?",
            (json.dumps(draft, ensure_ascii=False) if draft else None, intent, now_iso(), session_id),
        )


def get_pending_intent(session_id: str) -> str | None:
    """读取上一轮挂起的意图，用于「追问 → 用户补充 → 恢复原任务」的状态机。"""
    row = get_session(session_id)
    return row.get("pending_intent") if row else None


def get_pending(session_id: str) -> dict | None:
    row = get_session(session_id)
    if not row or not row.get("pending_ticket"):
        return None
    try:
        return json.loads(row["pending_ticket"])
    except (ValueError, TypeError):
        return None


def add_message(
    session_id: str, role: str, content: str, intent: str | None = None,
    sources: list | None = None, trace: list | None = None,
    tool_results: list | None = None,
) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO messages "
            "(session_id, role, content, intent, sources, trace, tool_results, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, role, content, intent,
                json.dumps(sources or [], ensure_ascii=False),
                json.dumps(trace or [], ensure_ascii=False),
                json.dumps(tool_results or [], ensure_ascii=False),
                now_iso(),
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE session_id = ?",
            (now_iso(), session_id),
        )
        return int(cursor.lastrowid or 0)


def get_messages(session_id: str, limit: int = 60) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    )
    rows.reverse()
    result = []
    for row in rows:
        for key in ("sources", "trace", "tool_results"):
            try:
                row[key] = json.loads(row[key] or "[]")
            except (ValueError, TypeError):
                row[key] = []
        result.append(row)
    return result


def history_for_llm(session_id: str, limit: int = 8) -> list[dict]:
    """给模型/规则决策器的上下文，只保留角色与内容。"""
    rows = get_messages(session_id, limit)
    return [{"role": row["role"], "content": row["content"][:600]} for row in rows]


def reset_session(session_id: str) -> None:
    """对话重置：清空该会话消息与待确认状态，保留同一个 session_id。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute(
            "UPDATE conversations SET pending_ticket = NULL, pending_intent = NULL, "
            "title = '新对话', updated_at = ? WHERE session_id = ?",
            (now_iso(), session_id),
        )


def delete_session(session_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
