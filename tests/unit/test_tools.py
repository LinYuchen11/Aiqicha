"""单元测试：工具注册表、参数校验、工单创建与状态查询、调用日志。"""
from __future__ import annotations

import pytest

from backend.core.errors import ToolError
from backend.database import ticket_repo, tool_repo
from backend.tools import build_ticket_draft, invoke, list_tool_infos


def test_registry_contains_three_tools():
    names = {item.name for item in list_tool_infos()}
    assert names == {"it_service_query", "ticket_create", "ticket_query"}
    for item in list_tool_infos():
        assert item.description and item.parameters.get("properties")


def test_it_service_query_executes_real_logic():
    result = invoke("it_service_query", {"keyword": "软件安装"})
    assert result["status"] == "成功"
    assert result["result"]["found"] is True
    assert result["result"]["count"] >= 1


def test_missing_tool_parameters_are_rejected():
    with pytest.raises(ToolError) as exc:
        invoke("ticket_query", {})
    assert "参数" in exc.value.message


def test_unknown_tool_rejected():
    with pytest.raises(ToolError):
        invoke("not_registered", {})


def test_ticket_create_requires_confirmation():
    with pytest.raises(ToolError) as exc:
        invoke("ticket_create", {
            "fault_type": "网络故障",
            "description": "办公电脑无法连接公司无线网络",
            "contact": "13800000000",
        })
    assert "确认" in exc.value.message
    assert ticket_repo.list_tickets() == []


def test_ticket_create_then_query():
    created = invoke("ticket_create", {
        "fault_type": "网络故障",
        "description": "办公电脑无法连接公司无线网络，重启后仍无法恢复",
        "contact": "13800000000",
        "confirmed": True,
    })
    ticket_no = created["result"]["ticket_no"]
    assert ticket_no.startswith("IT-")
    queried = invoke("ticket_query", {"ticket_no": ticket_no})
    assert queried["result"]["found"] is True
    assert queried["result"]["ticket"]["status"] == "待受理"


def test_ticket_query_unknown_number():
    result = invoke("ticket_query", {"ticket_no": "IT-20260101-9999"})
    assert result["result"]["found"] is False


def test_tool_calls_are_logged():
    invoke("it_service_query", {"keyword": "VPN"})
    logs = tool_repo.list_tool_logs()
    assert logs
    assert logs[0]["status"] == "成功"
    assert logs[0]["tool_name"] == "it_service_query"
    assert logs[0]["args_json"] == {"keyword": "VPN"}


def test_draft_requires_contact():
    draft = build_ticket_draft("电脑连不上网络", {}, [])
    assert draft["complete"] is False
    assert any("联系方式" in item for item in draft["missing"])
