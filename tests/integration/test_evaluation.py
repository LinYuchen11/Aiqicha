"""集成测试：评估中心真实运行实验并计算指标（不填充虚构数据）。"""
from __future__ import annotations

from backend.services import evaluation_service

QUESTIONS = [
    {
        "id": "T01", "类型": "简单查询", "问题": "年假提前几天申请？",
        "检索问题": "年假提前几个工作日申请", "标准答案": "提前 3 个工作日",
        "相关文档": ["模拟考勤制度.md"], "相关章节": ["年假"], "评估类型": "检索评估",
    },
    {
        "id": "T02", "类型": "条件查询", "问题": "调休多久内使用？",
        "检索问题": "加班调休需要在多少天内使用", "标准答案": "30 天内",
        "相关文档": ["模拟考勤制度.md"], "相关章节": ["加班与调休"], "评估类型": "检索评估",
    },
    {
        "id": "T03", "类型": "无答案问题", "问题": "有住房补贴吗？",
        "检索问题": "公司是否提供免费住房补贴和购房贷款", "标准答案": "知识库无相关规定",
        "相关文档": [], "相关章节": [], "评估类型": "检索评估",
    },
    {
        "id": "T04", "类型": "工具调用", "问题": "帮我创建工单",
        "检索问题": "创建工单", "标准答案": "由工具执行",
        "相关文档": [], "相关章节": [], "评估类型": "工具调用",
    },
]

DOC = """# 模拟考勤制度
> 模拟企业制度文档。

## 一、年假申请规定
员工申请年假需提前 3 个工作日提交申请，部门负责人在 2 个工作日内审批。

## 二、加班与调休规定
加班需提前登记，调休应在加班发生后 30 天内使用，逾期未使用自动失效。
"""


def test_topk_experiment_produces_real_metrics(api_client, monkeypatch):
    api_client.post("/api/documents/upload", files=[("files", ("模拟考勤制度.md", DOC.encode("utf-8")))])
    monkeypatch.setattr("backend.services.evaluation_service.load_questions", lambda: QUESTIONS)
    result = evaluation_service.run_experiment("topk", {})
    assert result["status"] == "已完成"
    rows = result["metrics"]["方案"]
    assert len(rows) == 3
    assert [row["方案"] for row in rows] == ["Top-3", "Top-5", "Top-10"]
    for row in rows:
        assert 0.0 <= row["Recall@K"] <= 1.0
        assert 0.0 <= row["MRR"] <= 1.0
        assert row["平均响应时间ms"] >= 0
        assert len(row["每题明细"]) == 3
    assert result["metrics"]["跳过工具调用题数"] == 1
    assert result["metrics"]["人工评估状态"].startswith("待人工评估")


def test_human_eval_is_separate_from_auto_metrics(api_client):
    from backend.models.schemas import HumanEvalRequest

    saved = evaluation_service.save_human_eval(
        HumanEvalRequest(question_id="T01", answer_correctness=1.0, citation_accuracy=1.0, note="人工判读")
    )
    assert saved["记录编号"] > 0
    summary = evaluation_service.human_evals()
    assert len(summary) == 1
    assert summary[0]["evaluator"] == "人工评估"


def test_unknown_experiment_rejected():
    from backend.core.errors import ParamError
    import pytest

    with pytest.raises(ParamError):
        evaluation_service.run_experiment("not_exist", {})
