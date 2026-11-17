"""工具参数契约：全部由 Pydantic 校验，缺失或非法参数会返回明确中文错误。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ITServiceQueryArgs(BaseModel):
    keyword: str = Field(default="", max_length=100, description="查询关键词，如软件安装、VPN、打印机")
    category: str | None = Field(default=None, description="服务类别，如 软件安装 / 账号权限 / 网络故障")

    @field_validator("keyword")
    @classmethod
    def strip_keyword(cls, value: str) -> str:
        return (value or "").strip()


class TicketDraft(BaseModel):
    fault_type: str = Field(min_length=2, max_length=50, description="故障类型，如 网络故障 / 软件安装")
    description: str = Field(min_length=5, max_length=1000, description="故障描述，需说明具体现象")
    contact: str = Field(min_length=2, max_length=100, description="联系方式，必须由用户提供，不得臆测")
    department: str = Field(default="", max_length=100, description="所属部门（可选）")
    urgency: Literal["普通", "紧急"] = Field(default="普通", description="紧急程度")


class TicketCreateArgs(TicketDraft):
    confirmed: bool = Field(default=False, description="用户是否已明确确认创建工单")
    session_id: str | None = Field(default=None, description="来源会话编号")


class TicketQueryArgs(BaseModel):
    ticket_no: str = Field(min_length=3, max_length=50, description="工单编号，如 IT-20261116-0001")

    @field_validator("ticket_no")
    @classmethod
    def strip_no(cls, value: str) -> str:
        return (value or "").strip()
