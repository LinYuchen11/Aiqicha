"""工具执行层：在此注册全部工具，Agent 只依赖 registry 接口。"""
from __future__ import annotations

from backend.tools.it_service import query_it_service
from backend.tools.registry import ToolSpec, get_spec, invoke, list_tool_infos, register
from backend.tools.schemas import ITServiceQueryArgs, TicketCreateArgs, TicketQueryArgs
from backend.tools.ticket import build_ticket_draft, create_ticket_tool, query_ticket_tool

register(
    ToolSpec(
        name="it_service_query",
        label="企业 IT 服务查询",
        description="查询常见 IT 服务信息、软件安装支持情况、账号权限办理渠道与处理时效（模拟数据，来自 SQLite）。",
        args_model=ITServiceQueryArgs,
        handler=query_it_service,
    )
)
register(
    ToolSpec(
        name="ticket_create",
        label="IT 服务工单创建",
        description="创建 IT 服务工单，自动生成工单编号并写入 SQLite。必须经用户确认后才会真正写库。",
        args_model=TicketCreateArgs,
        handler=create_ticket_tool,
        requires_confirmation=True,
    )
)
register(
    ToolSpec(
        name="ticket_query",
        label="工单状态查询",
        description="按工单编号查询创建时间、故障类型、当前状态与处理说明。",
        args_model=TicketQueryArgs,
        handler=query_ticket_tool,
    )
)

__all__ = [
    "invoke", "list_tool_infos", "get_spec", "build_ticket_draft",
    "ToolSpec", "register",
]
