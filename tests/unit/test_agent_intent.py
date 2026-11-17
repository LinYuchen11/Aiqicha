"""单元测试：7 类意图识别、上下文指代改写、任务规划分支。"""
from __future__ import annotations

import pytest

from backend.agent.intent import INTENT_LABELS, classify, resolve_query
from backend.agent.planner import ROUTES, plan_steps
from backend.llm.client import LLMClient


@pytest.mark.parametrize(
    "message,expected",
    [
        ("年假需要提前几天申请？", "knowledge_query"),
        ("电脑无法连接公司网络怎么办？", "it_consult"),
        ("帮我创建工单", "ticket_create"),
        ("查询工单 IT-20261116-0001 的状态", "ticket_query"),
        ("如果查不到解决办法就帮我创建工单", "multi_step"),
        ("你好", "chitchat"),
        ("帮我写一个手机游戏", "unknown"),
    ],
)
def test_intent_classification(message, expected):
    result = classify(message, [], LLMClient())
    assert result["intent"] == expected
    assert result["intent"] in INTENT_LABELS


def test_ticket_number_slot_extracted():
    result = classify("查询工单 IT-20261116-0001 的处理进度", [], LLMClient())
    assert result["slots"].get("ticket_no") == "IT-20261116-0001"


def test_followup_resolves_with_history():
    history = [
        {"role": "user", "content": "公司电脑如何申请软件安装权限？"},
        {"role": "assistant", "content": "需提交 IT 服务台工单。"},
    ]
    resolved = resolve_query("那如果是设计软件呢？", history)
    assert "软件安装权限" in resolved
    assert "补充条件" in resolved


def test_standalone_question_not_rewritten():
    resolved = resolve_query("差旅报销需要哪些材料？", [])
    assert "补充条件" not in resolved


def test_planner_routes_are_defined():
    client = LLMClient()
    for intent, expected in ROUTES.items():
        result = plan_steps(intent, "测试消息", {}, client)
        assert result["route"] == expected
        assert result["steps"]
