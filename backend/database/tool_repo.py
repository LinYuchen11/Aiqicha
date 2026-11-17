"""工具调用日志仓储：记录调用时间、参数、结果、状态与耗时。"""
from __future__ import annotations

import json

from backend.database.db import fetch_all, fetch_one, get_conn, now_iso


def log_tool(
    session_id: str | None, tool_name: str, args: dict, result: dict | None,
    status: str, error_msg: str = "", elapsed_ms: float = 0.0,
) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO tool_logs "
            "(session_id, tool_name, args_json, result_json, status, error_msg, elapsed_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, tool_name,
                json.dumps(args, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                status, error_msg, round(elapsed_ms, 2), now_iso(),
            ),
        )
        return int(cursor.lastrowid or 0)


def list_tool_logs(limit: int = 100, tool_name: str | None = None) -> list[dict]:
    if tool_name:
        rows = fetch_all(
            "SELECT * FROM tool_logs WHERE tool_name = ? ORDER BY id DESC LIMIT ?",
            (tool_name, limit),
        )
    else:
        rows = fetch_all("SELECT * FROM tool_logs ORDER BY id DESC LIMIT ?", (limit,))
    for row in rows:
        for key in ("args_json", "result_json"):
            try:
                row[key] = json.loads(row[key] or "{}")
            except (ValueError, TypeError):
                row[key] = {}
    return rows


def tool_stats() -> dict:
    rows = fetch_all("SELECT status, COUNT(*) AS n FROM tool_logs GROUP BY status")
    total = fetch_one("SELECT COUNT(*) AS n FROM tool_logs")
    return {
        "调用总数": int(total["n"]) if total else 0,
        "成功": sum(int(r["n"]) for r in rows if r["status"] == "成功"),
        "失败": sum(int(r["n"]) for r in rows if r["status"] == "失败"),
    }
