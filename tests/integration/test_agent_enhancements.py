"""第二轮 Agent 增强专项测试：多工具连续执行、结果驱动路由、决策来源、追问恢复。"""
from __future__ import annotations

from backend.agent.tool_guard import sanitize_tool_results


def _chat(client, message: str, session_id: str | None = None) -> dict:
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_multi_tool_continuous_execution(api_client):
    """一次请求连续执行两个不同工具，且第二个工具在第一个成功有结果后才执行。"""
    body = _chat(
        api_client,
        "先查一下 VPN 相关的 IT 服务，如果有对应服务，再帮我查询工单 IT-20261116-0001 的状态",
    )
    assert body["intent"] == "multi_tool", body["intent"]
    tools = [item["tool"] for item in body["tool_results"]]
    assert tools == ["it_service_query", "ticket_query"], tools
    assert "多工具连续执行结果" in body["answer"]
    assert [step["stage"] for step in body["trace"]].count("工具执行") == 2


def test_next_tool_depends_on_previous_result(api_client):
    """第一步工具没查到服务时，不得继续第二个工具（依据结果内容分支）。"""
    body = _chat(
        api_client,
        "先查一下 量子传真机XYZ 相关的 IT 服务，再帮我查询工单 IT-20261116-0001 的状态",
    )
    assert body["intent"] == "multi_tool"
    tools = [item["tool"] for item in body["tool_results"]]
    assert tools == ["it_service_query"], tools
    assert [step["stage"] for step in body["trace"]].count("工具执行") == 1


def test_decision_source_is_machine_readable(api_client):
    body = _chat(api_client, "年假需要提前几天申请？")
    assert body["decision_source"], "意图决策来源必须下发给前端"
    assert body["plan_source"], "任务规划来源必须下发给前端"
    assert isinstance(body["fallback"], bool)
    assert any(step.get("decision_source") for step in body["trace"])


def test_supplement_resumes_pending_ticket(api_client):
    """追问联系方式后，纯补答能恢复工单创建意图并保留原故障描述。"""
    session_id = "test-supplement-session"
    first = _chat(api_client, "帮我创建工单，办公电脑无法连接公司无线网络", session_id)
    assert first["intent"] == "ticket_create"
    assert "联系方式" in first["answer"]

    second = _chat(api_client, "联系方式 13800000000", session_id)
    assert second["intent"] == "ticket_create", second["intent"]
    assert second["pending_confirmation"], "补齐信息后应生成待确认工单"
    fields = second["pending_confirmation"]["字段"]
    assert fields["contact"] == "13800000000"
    assert "无法连接公司无线网络" in fields["description"]


def test_forged_tool_results_are_dropped():
    """模型普通文本或未注册工具名不能被当成真实工具执行成功。"""
    clean, dropped = sanitize_tool_results([
        {"tool": "ticket_query", "status": "成功", "result": {"found": True}, "elapsed_ms": 1.0},
        {"tool": "fake_tool", "status": "成功", "result": {}, "elapsed_ms": 1.0},
        {"tool": "ticket_query", "status": "编造成功", "result": {}, "elapsed_ms": 1.0},
        "模型说：工单已创建成功",
    ])
    assert len(clean) == 1
    assert dropped == 3
    assert clean[0]["tool"] == "ticket_query"
