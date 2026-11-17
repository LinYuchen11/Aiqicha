"""IT 服务目录与工单仓储。工单号在事务内生成，写入后重启仍可查询。"""
from __future__ import annotations

from datetime import datetime

from backend.database.db import fetch_all, fetch_one, get_conn, now_iso


def next_ticket_no() -> str:
    prefix = f"IT-{datetime.now().strftime('%Y%m%d')}-"
    row = fetch_one("SELECT COUNT(*) AS n FROM tickets WHERE ticket_no LIKE ?", (prefix + "%",))
    return f"{prefix}{int(row['n']) + 1 if row else 1:04d}"


def create_ticket(
    fault_type: str, description: str, contact: str,
    department: str = "", urgency: str = "普通", session_id: str | None = None,
) -> dict:
    now = now_iso()
    with get_conn() as conn:
        for _ in range(5):
            ticket_no = next_ticket_no_in(conn)
            try:
                cursor = conn.execute(
                    "INSERT INTO tickets "
                    "(ticket_no, fault_type, description, contact, department, urgency, "
                    " status, handling_note, session_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, '待受理', ?, ?, ?, ?)",
                    (
                        ticket_no, fault_type, description, contact, department, urgency,
                        "工单已创建，等待 IT 服务台受理（模拟流程）。", session_id, now, now,
                    ),
                )
                break
            except Exception:
                continue
        else:
            raise RuntimeError("工单号生成失败")
        ticket_id = int(cursor.lastrowid or 0)
    return get_ticket(ticket_no) or {"id": ticket_id, "ticket_no": ticket_no}


def next_ticket_no_in(conn) -> str:
    prefix = f"IT-{datetime.now().strftime('%Y%m%d')}-"
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM tickets WHERE ticket_no LIKE ?", (prefix + "%",)
    ).fetchone()
    return f"{prefix}{int(row['n']) + 1 if row else 1:04d}"


def get_ticket(ticket_no: str) -> dict | None:
    return fetch_one("SELECT * FROM tickets WHERE ticket_no = ?", (ticket_no.strip(),))


def list_tickets(limit: int = 100) -> list[dict]:
    return fetch_all("SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (limit,))


def list_it_services(category: str | None = None, keyword: str = "") -> list[dict]:
    rows = fetch_all("SELECT * FROM it_services ORDER BY service_key")
    result = []
    key = (keyword or "").strip().lower()
    for row in rows:
        if category and row["category"] != category:
            continue
        haystack = f"{row['name']} {row['description']} {row['category']}".lower()
        if key and key not in haystack:
            continue
        item = dict(row)
        item["supported"] = bool(item["supported"])
        result.append(item)
    return result


def get_it_service(service_key: str) -> dict | None:
    return fetch_one("SELECT * FROM it_services WHERE service_key = ?", (service_key,))
