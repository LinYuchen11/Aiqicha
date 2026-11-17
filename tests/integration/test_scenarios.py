"""集成测试：场景 A–G，全部通过真实 HTTP 路由与临时 SQLite 运行，不产生 API 费用。"""
from __future__ import annotations

import pytest

DOC_HR = """# 模拟企业考勤与请假制度
> 本文件为模拟企业制度文档，仅用于测试。

## 一、年假申请规定
员工申请年假需提前 3 个工作日提交申请，由部门负责人在 2 个工作日内审批。工作满 1 年不满 5 年每年享有 5 天年假。

## 二、加班与调休规定
加班需提前在系统登记，调休应在加班发生后 30 天内使用，逾期未使用自动失效。忘打卡需在 2 个工作日内补卡。

## 三、考勤与报销衔接
考勤异常补卡记录会同步到月度考勤汇总，作为差旅报销审批的参考依据之一。
"""

DOC_FIN = """# 模拟企业差旅及费用报销制度
> 本文件为模拟企业制度文档，仅用于测试。

## 一、差旅报销时限
差旅费用报销需在出差结束后 5 个工作日内提交报销单，并附出差审批单与票据。

## 二、报销标准与限额
市内交通费按实际票据报销，单日上限 200 元；住宿费按城市分级标准执行，超出部分需事前审批。

## 三、与考勤制度的关联
报销审批会参考月度考勤汇总中的异常记录，考勤异常未处理时报销单将被退回补充。
"""

DOC_IT = """# 模拟企业 IT 服务及账号权限管理规范
> 本文件为模拟企业制度文档，仅用于测试。

## 一、软件安装与许可证管理
常用办公软件由 IT 服务台统一推送安装。设计类专业软件需部门负责人审批后安装，许可证数量有限，办理时效为 3 个工作日。

## 二、网络连接故障处理
办公电脑无法连接公司无线网络时，先检查域账号状态与无线证书，再重启网卡并更新驱动。仍无法恢复可提交 IT 服务工单。

## 三、账号权限申请
本地管理员权限默认不开放，确需使用时需提交用途说明并经部门负责人与信息安全双审批。
"""


def _upload(client, name: str, text: str):
    return client.post("/api/documents/upload", files=[("files", (name, text.encode("utf-8")))])


def _new_session(client) -> str:
    return client.post("/api/sessions").json()["会话"]["session_id"]


def test_scenario_a_knowledge_qa(api_client):
    """场景 A：上传 → 解析 → 分块 → 向量化 → 提问 → 检索 → 生成 → 带来源答案。"""
    uploaded = _upload(api_client, "模拟考勤制度.md", DOC_HR)
    assert uploaded.json()["成功数"] == 1
    overview = api_client.get("/api/documents").json()
    assert overview["统计"]["处理成功"] == 1
    assert overview["统计"]["文本块总数"] >= 2
    assert overview["向量数量"] >= 2

    response = api_client.post("/api/chat", json={
        "session_id": _new_session(api_client),
        "message": "年假需要提前几个工作日申请？", "top_k": 5,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["sources"], "应返回真实知识来源"
    assert body["sources"][0]["doc_name"] == "模拟考勤制度.md"
    assert body["sources"][0]["section"]
    assert "模拟运行" in body["answer"]
    assert any(step["stage"] == "意图识别" for step in body["trace"])
    assert any(step["stage"] == "知识检索" for step in body["trace"])


def test_scenario_b_cross_document(api_client):
    """场景 B：跨文档综合查询，返回多个真实来源。"""
    _upload(api_client, "模拟考勤制度.md", DOC_HR)
    _upload(api_client, "模拟报销制度.md", DOC_FIN)
    body = api_client.post("/api/chat", json={
        "session_id": _new_session(api_client),
        "message": "年假申请和差旅报销分别需要提前几个工作日？", "top_k": 10,
    }).json()
    names = {source["doc_name"] for source in body["sources"]}
    assert len(names) >= 2, f"应召回多个文档，实际：{names}"
    assert "模拟考勤制度.md" in names and "模拟报销制度.md" in names


def test_scenario_c_it_fault_consult(api_client):
    """场景 C：IT 故障咨询 → 意图识别 → 工具调用 + 知识检索 → 处理建议。"""
    _upload(api_client, "模拟IT服务规范.md", DOC_IT)
    body = api_client.post("/api/chat", json={
        "session_id": _new_session(api_client),
        "message": "电脑无法连接公司网络怎么办？",
    }).json()
    assert body["intent"] == "it_consult"
    assert any(item["tool"] == "it_service_query" for item in body["tool_results"])
    assert any(step["stage"] == "知识检索" for step in body["trace"])
    assert any(step["tool"] == "it_service_query" for step in body["trace"])
    assert body["sources"]


def test_scenario_d_ticket_create_with_confirmation(api_client):
    """场景 D：收集信息 → 用户确认 → 真实写库 → 返回工单编号 → 状态查询。"""
    sid = _new_session(api_client)
    first = api_client.post("/api/chat", json={
        "session_id": sid,
        "message": "帮我创建工单，办公电脑无法连接公司无线网络，联系方式 13800000000",
    }).json()
    assert first["pending_confirmation"] is not None
    assert first["intent"] == "ticket_create"

    pending = api_client.get(f"/api/sessions/{sid}/pending").json()["待确认工单"]
    assert pending["contact"] == "13800000000"
    assert api_client.get("/api/tools/tickets").json()["工单"] == [], "确认前不得写库"

    confirmed = api_client.post("/api/chat/confirm", json={
        "session_id": sid, "confirm": True,
    }).json()
    successful = [item for item in confirmed["tool_results"] if item["status"] == "成功"]
    assert successful and successful[-1]["tool"] == "ticket_create"
    ticket_no = successful[-1]["result"]["ticket_no"]
    assert ticket_no.startswith("IT-")
    assert len(api_client.get("/api/tools/tickets").json()["工单"]) == 1
    assert api_client.get(f"/api/sessions/{sid}/pending").json()["待确认工单"] is None

    queried = api_client.post("/api/chat", json={
        "session_id": sid, "message": f"查询工单 {ticket_no} 的状态",
    }).json()
    assert queried["intent"] == "ticket_query"
    assert ticket_no in queried["answer"]
    assert "待受理" in queried["answer"]


def test_scenario_e_multi_turn_context(api_client):
    """场景 E：连续对话，第二轮追问理解指代并复用上下文。"""
    _upload(api_client, "模拟IT服务规范.md", DOC_IT)
    sid = _new_session(api_client)
    api_client.post("/api/chat", json={
        "session_id": sid, "message": "公司电脑如何申请软件安装权限？",
    })
    second = api_client.post("/api/chat", json={
        "session_id": sid, "message": "那如果是设计软件呢？",
    }).json()
    assert any("上下文改写" in step["detail"] for step in second["trace"])
    assert second["sources"]
    history = api_client.get(f"/api/sessions/{sid}/messages").json()["消息"]
    assert len(history) == 4


def test_scenario_f_no_answer(api_client):
    """场景 F：知识库不存在的信息，明确告知资料不足，不编造制度。"""
    _upload(api_client, "模拟考勤制度.md", DOC_HR)
    body = api_client.post("/api/chat", json={
        "session_id": _new_session(api_client),
        "message": "公司是否提供免费住房补贴？",
    }).json()
    assert body["sources"] == []
    assert "没有检索到" in body["answer"] or "资料不足" in body["answer"]
    assert "不得编造" not in body["answer"] or "资料不足" in body["answer"]


def test_scenario_g_exception_handling(api_client):
    """场景 G：无效参数、空检索、解析失败、参数不完整、未确认、API 失败、上下文丢失。"""
    assert api_client.post("/api/chat", json={"message": "测试", "top_k": 0}).status_code == 400

    empty = api_client.post("/api/documents/upload", files=[("files", ("empty.txt", b""))]).json()
    assert empty["结果"][0]["成功"] is False
    assert "空" in empty["结果"][0]["错误说明"]

    bad_type = api_client.post("/api/documents/upload", files=[("files", ("bad.exe", b"x"))]).json()
    assert bad_type["结果"][0]["成功"] is False

    empty_search = api_client.post("/api/retrieval/search", json={"query": "年假", "top_k": 3}).json()
    assert empty_search["results"] == []
    assert "没有可检索" in empty_search["message"]

    missing = api_client.post("/api/tools/invoke", json={"tool_name": "ticket_query", "args": {}})
    assert missing.status_code == 400

    unconfirmed = api_client.post("/api/tools/invoke", json={
        "tool_name": "ticket_create",
        "args": {"fault_type": "网络故障", "description": "无法连接无线网络",
                 "contact": "13800000000", "confirmed": False},
    })
    assert unconfirmed.status_code == 400
    assert api_client.get("/api/tools/tickets").json()["工单"] == []

    from backend.core.errors import LLMError
    from backend.llm.client import LLMClient

    client = LLMClient()
    client.mode = "deepseek"
    client.api_key = "unit-test-key"
    client.base_url = "http://127.0.0.1:9"
    with pytest.raises(LLMError):
        client.complete("系统", "用户")

    recovered = api_client.post("/api/chat", json={
        "session_id": "不存在的会话编号", "message": "你好",
    })
    assert recovered.status_code == 200
    assert recovered.json()["session_id"] == "不存在的会话编号"
