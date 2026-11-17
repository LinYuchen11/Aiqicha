"""评估实验与人工评估仓储。自动指标与人工评分物理隔离，避免混淆。"""
from __future__ import annotations

import json
import uuid

from backend.database.db import fetch_all, fetch_one, get_conn, now_iso


def create_run(experiment: str, params: dict, embedding_mode: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO eval_runs "
            "(id, experiment, params, metrics, status, embedding_mode, started_at, finished_at, notes) "
            "VALUES (?, ?, ?, NULL, '运行中', ?, ?, NULL, NULL)",
            (run_id, experiment, json.dumps(params, ensure_ascii=False), embedding_mode, now_iso()),
        )
    return run_id


def finish_run(run_id: str, metrics: dict, status: str = "已完成", notes: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE eval_runs SET metrics = ?, status = ?, finished_at = ?, notes = ? WHERE id = ?",
            (json.dumps(metrics, ensure_ascii=False), status, now_iso(), notes, run_id),
        )


def list_runs(limit: int = 50) -> list[dict]:
    rows = fetch_all("SELECT * FROM eval_runs ORDER BY started_at DESC LIMIT ?", (limit,))
    for row in rows:
        for key in ("params", "metrics"):
            try:
                row[key] = json.loads(row[key] or "{}")
            except (ValueError, TypeError):
                row[key] = {}
    return rows


def get_run(run_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM eval_runs WHERE id = ?", (run_id,))
    if not row:
        return None
    for key in ("params", "metrics"):
        try:
            row[key] = json.loads(row[key] or "{}")
        except (ValueError, TypeError):
            row[key] = {}
    return row


def add_items(run_id: str, scheme: str, items: list[dict]) -> None:
    rows = [
        (
            run_id, scheme, item["question_id"], json.dumps(item["retrieved"], ensure_ascii=False),
            item["recall_at_k"], item["reciprocal_rank"], item["hit"], item["elapsed_ms"],
            item.get("context_support"),
        )
        for item in items
    ]
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO eval_items "
            "(run_id, scheme, question_id, retrieved, recall_at_k, reciprocal_rank, hit, elapsed_ms, context_support) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def get_items(run_id: str) -> list[dict]:
    rows = fetch_all("SELECT * FROM eval_items WHERE run_id = ? ORDER BY id", (run_id,))
    for row in rows:
        try:
            row["retrieved"] = json.loads(row["retrieved"] or "[]")
        except (ValueError, TypeError):
            row["retrieved"] = []
    return rows


def add_human_eval(
    run_id: str | None, question_id: str, answer_correctness: float | None,
    citation_accuracy: float | None, note: str, evaluator: str,
) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO human_evals "
            "(run_id, question_id, answer_correctness, citation_accuracy, note, evaluator, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, question_id, answer_correctness, citation_accuracy, note, evaluator, now_iso()),
        )
        return int(cursor.lastrowid or 0)


def list_human_evals(run_id: str | None = None) -> list[dict]:
    if run_id:
        return fetch_all(
            "SELECT * FROM human_evals WHERE run_id = ? ORDER BY id DESC", (run_id,)
        )
    return fetch_all("SELECT * FROM human_evals ORDER BY id DESC LIMIT 200")


def human_eval_summary() -> dict:
    rows = list_human_evals()
    scored_correct = [r["answer_correctness"] for r in rows if r["answer_correctness"] is not None]
    scored_citation = [r["citation_accuracy"] for r in rows if r["citation_accuracy"] is not None]
    return {
        "已录入条数": len(rows),
        "答案正确性已评分数": len(scored_correct),
        "来源引用已评分数": len(scored_citation),
        "答案正确性均值": round(sum(scored_correct) / len(scored_correct), 4) if scored_correct else None,
        "来源引用均值": round(sum(scored_citation) / len(scored_citation), 4) if scored_citation else None,
        "状态": "待人工评估" if not rows else "人工评估进行中",
    }
