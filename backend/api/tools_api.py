"""工具管理接口：工具清单、参数 schema、真实调用与执行记录。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.database.ticket_repo import list_tickets
from backend.database.tool_repo import list_tool_logs, tool_stats
from backend.models.schemas import ToolInvokeRequest
from backend.tools import invoke, list_tool_infos

router = APIRouter(prefix="/api/tools", tags=["工具管理"])


@router.get("")
def tools() -> dict:
    return {
        "工具": [item.model_dump() for item in list_tool_infos()],
        "统计": tool_stats(),
    }


@router.get("/logs")
def logs(limit: int = 100, tool_name: str | None = None) -> dict:
    return {"记录": list_tool_logs(limit=limit, tool_name=tool_name)}


@router.post("/invoke")
def invoke_tool(req: ToolInvokeRequest) -> dict:
    return invoke(req.tool_name, req.args, req.session_id)


@router.get("/tickets")
def tickets(limit: int = 100) -> dict:
    return {"工单": list_tickets(limit)}
