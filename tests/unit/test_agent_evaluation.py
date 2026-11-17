"""Agent 专项评估的指标计算边界测试。

使用 conftest 提供的 isolated_db fixture（每个用例独立临时 SQLite），保证不污染
真实运行库与其它测试。重点验证：
- 整次评估无任何工具调用时，工具执行成功率记为「无样本」，不误记为 100%；
- 空期望工具的集合比较正确、且工具选择准确率分母只统计有期望工具的题；
- 全命中时四项指标为 1.0；
- run_agent_evaluation() 真实链路在隔离环境下可运行并返回完整结构。
"""
from __future__ import annotations

from backend.services.agent_evaluation_service import (
    aggregate_metrics,
    run_agent_evaluation,
    tools_match,
)


def _detail(
    intent_hit: bool = True,
    expected_tools: list[str] | None = None,
    tools_equal: bool = True,
    statuses: list[str] | None = None,
    completed: bool = True,
) -> dict:
    """构造 aggregate_metrics 所需的最小逐题明细。"""
    expected = list(expected_tools or [])
    return {
        "题号": "T",
        "意图命中": intent_hit,
        "工具选择计入分母": len(expected) > 0,
        "工具集合一致": tools_equal,
        "工具状态": list(statuses or []),
        "是否完成": completed,
    }


def test_tool_execution_success_rate_no_samples_is_not_100_percent(isolated_db):
    """边界：所有题都无工具调用 → 工具执行成功率必须是「无样本」，绝不能填 1.0。"""
    details = [_detail(statuses=[]) for _ in range(3)]
    metrics = aggregate_metrics(details)
    exec_rate = metrics["工具执行成功率"]
    assert exec_rate["总调用"] == 0
    assert exec_rate["无样本"] is True
    assert exec_rate["值"] is None
    assert exec_rate["值"] != 1.0  # 明确防止「无样本被误记为 100%」


def test_empty_expected_tools_scoring(isolated_db):
    """边界：空期望工具的集合比较正确，且只把「有期望工具」的题计入工具选择准确率分母。"""
    # 空集合也要正确计分：空集 == 空集 为 True；空集 != 非空集 为 False
    assert tools_match([], []) is True
    assert tools_match([], ["ticket_query"]) is False
    assert tools_match(["it_service_query"], ["it_service_query"]) is True
    assert tools_match(["ticket_query"], ["it_service_query"]) is False

    details = [
        _detail(expected_tools=["it_service_query"], tools_equal=True, statuses=["成功"]),
        _detail(expected_tools=["ticket_query"], tools_equal=False, statuses=["失败"]),
        # 下面 3 题期望工具为空：集合比较为 True，但不应计入分母
        _detail(expected_tools=[], tools_equal=True, statuses=[]),
        _detail(expected_tools=[], tools_equal=True, statuses=[]),
        _detail(expected_tools=[], tools_equal=True, statuses=[]),
    ]
    metrics = aggregate_metrics(details)
    tool_acc = metrics["工具选择准确率"]
    assert tool_acc["有期望工具题数"] == 2          # 只统计非空期望工具的题
    assert tool_acc["命中"] == 1
    assert tool_acc["值"] == 0.5
    # 空期望工具题的集合比较结果仍如实写入明细，未被误改
    assert all(d["工具集合一致"] is True for d in details[2:])


def test_aggregate_metrics_all_match(isolated_db):
    """正常边界：全部命中且工具全部成功时，四项指标均为 1.0。"""
    details = [
        _detail(expected_tools=["it_service_query"], tools_equal=True, statuses=["成功"]),
        _detail(expected_tools=["ticket_query"], tools_equal=True, statuses=["成功"]),
        _detail(expected_tools=[], tools_equal=True, statuses=[]),
    ]
    metrics = aggregate_metrics(details)
    assert metrics["总题数"] == 3
    assert metrics["意图识别准确率"]["值"] == 1.0
    assert metrics["工具选择准确率"]["值"] == 1.0
    assert metrics["工具执行成功率"]["值"] == 1.0
    assert metrics["工具执行成功率"]["无样本"] is False
    assert metrics["任务完成率"]["值"] == 1.0


def test_run_agent_evaluation_structure(isolated_db):
    """真实链路 smoke：隔离环境下 run_agent_evaluation() 能真实跑通并返回完整结构。

    isolated_db 保证该用例使用独立临时库；函数内部还会再重定向到自己的临时目录并恢复。
    断言只覆盖返回结构，不绑定具体数值，避免依赖正在演进的业务代码。
    """
    data = run_agent_evaluation()
    assert isinstance(data, dict)
    assert data["题数"] == len(data["逐题明细"]) > 0
    for key in ("意图识别准确率", "工具选择准确率", "工具执行成功率", "任务完成率"):
        assert key in data["指标"]
    assert "Mock" in data["运行环境"]["决策器"] or data["运行环境"]["是否 Mock"] is True
    assert "真实 DeepSeek 模式下未验证" in data["结论标注"]
