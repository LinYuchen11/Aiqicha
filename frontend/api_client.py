"""前端与 FastAPI 后端通信的唯一入口，所有页面通过本模块真实调用接口。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 180


class ApiError(Exception):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


def _request(method: str, path: str, **kwargs) -> Any:
    try:
        response = requests.request(method, f"{BASE_URL}{path}", timeout=TIMEOUT, **kwargs)
    except requests.Timeout as exc:
        raise ApiError("后端请求超时", "实验运行可能需要较长时间，请稍后重试") from exc
    except requests.RequestException as exc:
        raise ApiError("无法连接后端服务", f"请先启动后端（{BASE_URL}）。详细信息：{exc}") from exc
    if response.status_code >= 400:
        try:
            error = (response.json() or {}).get("错误", {})
        except ValueError:
            error = {}
        raise ApiError(
            error.get("错误信息") or f"请求失败（HTTP {response.status_code}）",
            error.get("详细说明", ""),
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError("后端返回格式异常", response.text[:200]) from exc


def health() -> dict:
    return _request("GET", "/api/health")


def config() -> dict:
    return _request("GET", "/api/config")


def upload_files(files: list[tuple[str, bytes]]) -> dict:
    multipart = [("files", (name, data)) for name, data in files]
    return _request("POST", "/api/documents/upload", files=multipart)


def list_documents() -> dict:
    return _request("GET", "/api/documents")


def document_detail(doc_id: str) -> dict:
    return _request("GET", f"/api/documents/{doc_id}")


def delete_document(doc_id: str) -> dict:
    return _request("DELETE", f"/api/documents/{doc_id}")


def reprocess_document(doc_id: str, chunk_size: int | None = None, overlap: int | None = None) -> dict:
    params = {k: v for k, v in {"chunk_size": chunk_size, "overlap": overlap}.items() if v is not None}
    return _request("POST", f"/api/documents/{doc_id}/reprocess", params=params)


def retrieval_search(payload: dict) -> dict:
    return _request("POST", "/api/retrieval/search", json=payload)


def chat(payload: dict) -> dict:
    return _request("POST", "/api/chat", json=payload)


def confirm(payload: dict) -> dict:
    return _request("POST", "/api/chat/confirm", json=payload)


def new_session() -> dict:
    return _request("POST", "/api/sessions")


def sessions(limit: int = 50) -> dict:
    return _request("GET", "/api/sessions", params={"limit": limit})


def messages(session_id: str) -> dict:
    return _request("GET", f"/api/sessions/{session_id}/messages")


def pending(session_id: str) -> dict:
    return _request("GET", f"/api/sessions/{session_id}/pending")


def reset_session(session_id: str) -> dict:
    return _request("POST", f"/api/sessions/{session_id}/reset")


def delete_session(session_id: str) -> dict:
    return _request("DELETE", f"/api/sessions/{session_id}")


def tools() -> dict:
    return _request("GET", "/api/tools")


def tool_logs(limit: int = 100, tool_name: str | None = None) -> dict:
    params = {"limit": limit}
    if tool_name:
        params["tool_name"] = tool_name
    return _request("GET", "/api/tools/logs", params=params)


def invoke_tool(name: str, args: dict, session_id: str | None = None) -> dict:
    return _request("POST", "/api/tools/invoke", json={"tool_name": name, "args": args, "session_id": session_id})


def tickets() -> dict:
    return _request("GET", "/api/tools/tickets")


def eval_overview() -> dict:
    return _request("GET", "/api/evaluation/overview")


def eval_questions() -> dict:
    return _request("GET", "/api/evaluation/questions")


def eval_runs() -> dict:
    return _request("GET", "/api/evaluation/runs")


def eval_run_detail(run_id: str) -> dict:
    return _request("GET", f"/api/evaluation/runs/{run_id}")


def run_evaluation(experiment: str, params: dict | None = None) -> dict:
    return _request("POST", "/api/evaluation/run", json={"experiment": experiment, "params": params or {}})


def save_human_eval(payload: dict) -> dict:
    return _request("POST", "/api/evaluation/human", json=payload)


def human_evals() -> dict:
    return _request("GET", "/api/evaluation/human")
