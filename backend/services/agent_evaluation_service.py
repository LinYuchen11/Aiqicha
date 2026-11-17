"""Agent 专项评估服务：真实调用 chat_service.chat() 并聚合四项指标。

评估对象为「Mock 规则决策器」（无 .env / 无 DeepSeek Key，规则决策器 + 规则规划器
+ 本地抽取式模拟器）。本模块的结论不得被写成真实大模型结果。

四项指标（计算口径同时写入「指标说明」，供报告引用，均为可程序判定、不接受主观填写）：
1. 意图识别准确率 = expected_intent 命中数 / 总题数；
2. 工具选择准确率 = 期望工具与实际工具名按集合比较相等的题数 / 有期望工具的题数
   （分母为 expected_tools 非空的题；空期望工具的题不纳入分母，但其集合比较仍按
   「空集 == 空集为命中」的规则正确计算并写入明细，避免被误判或错误计入分母）；
3. 工具执行成功率 = 所有实际工具调用中 status == "成功" 的比例；整次运行没有任何
   工具调用时如实记为「无样本」（值为 None），绝不填 1.0；
4. 任务完成率 = 按每题 completion_rule 由代码确定性判定「是否完成」，完成题数 / 总题数。

隔离方式（选用方案 A：函数内部重定向到临时目录）：
run_agent_evaluation() 内部把 settings.db_path / upload_dir / vector_dir 指向临时目录，
重置 db._initialized 后调用 init_database() 与 ensure_sample_documents()，结束时在
finally 中恢复 settings 原始值与 db._initialized，并删除临时目录。因此不会读写真实
运行库，也不会污染其它测试；脚本 scripts/run_agent_evaluation.py 直接调用本函数即可。
样本文档目录 sample_dir 保持只读的真实路径，仅把「写入」导向临时库。
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# 完成判定规则表：每个标识对应一组确定性、可程序判定的与条件。
# 所有规则都隐含「基础完成」：无异常 + answer 非空 + 不含失败标志 + 待确认状态符合预期。
RULE_DEFINITIONS: dict[str, str] = {
    "answer": "仅基础完成：回答非空、无异常、不含失败标志、pending_confirmation 有无与 needs_confirmation 一致。",
    "answer_and_sources": "基础完成 + 返回至少 1 条知识来源（sources 非空）。",
    "answer_and_tool_items": "基础完成 + 工具结果的 result 含 IT 服务目录条目（items 为列表）。",
    "answer_and_tool_found": "基础完成 + 工具结果的 result 含 found 字段（查到或未查到都如实给出结论）。",
    "answer_and_pending": "基础完成 + 返回待确认工单（pending_confirmation 为字典且「字段」为非空字典）。",
    "answer_and_clarify": "基础完成 + 信息不足时主动追问（回答含「请提供/请补充/还需要」之一、无工具调用、无待确认单）。",
    "answer_and_no_answer": "基础完成 + 知识库无命中时如实拒答（sources 为空且回答含「没有检索到」或「无法据此给出」）。",
}

# 四项指标的计算口径，写进报告，保证透明可复核。
METRIC_DEFINITIONS: dict[str, str] = {
    "意图识别准确率": "expected_intent 与 ChatResponse.intent 相等计为命中；命中数 / 总题数。",
    "工具选择准确率": "逐题比较 set(expected_tools) 与 set(实际工具名)，相等计命中；分母为 expected_tools 非空的题数。空期望工具的题不纳入分母（明细记为「不适用」），但其集合比较仍按空集相等规则正确计算并写入明细。",
    "工具执行成功率": "汇总所有题 tool_results 中 status == '成功' 的比例；整次运行没有任何工具调用时记为「无样本」（值为 None），不填 1.0。",
    "任务完成率": "按每题 completion_rule 由代码确定性判定是否完成（见完成判定规则表），完成题数 / 总题数；不接受人工填写的完成标记。",
}

QUESTION_FILE = Path(__file__).resolve().parents[2] / "data" / "evaluation" / "agent_questions.json"

_REQUIRED_FIELDS = (
    "id", "message", "类别", "expected_intent", "expected_tools",
    "needs_confirmation", "expected_completion", "completion_rule",
)


def load_questions(path: Path | str | None = None) -> list[dict]:
    """读取人工标注题集并做最小校验，返回问题列表。"""
    file = Path(path) if path else QUESTION_FILE
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    questions = data.get("问题集")
    if not isinstance(questions, list) or not questions:
        raise ValueError("标注题集为空或格式错误：缺少「问题集」列表")
    for item in questions:
        missing = [key for key in _REQUIRED_FIELDS if key not in item]
        if missing:
            raise ValueError(f"标注题 {item.get('id', '?')} 缺少字段：{missing}")
        if item["completion_rule"] not in RULE_DEFINITIONS:
            raise ValueError(f"标注题 {item['id']} 使用了未定义的完成规则：{item['completion_rule']}")
    return questions


def _extract_tools(response: Any) -> list[str]:
    """从 ChatResponse.tool_results 提取去重、排序后的工具名列表。"""
    results = getattr(response, "tool_results", None) or []
    return sorted({str(item.get("tool", "")) for item in results if item.get("tool")})


def _tool_statuses(response: Any) -> list[str]:
    """提取该题所有工具调用的 status 列表（用于工具执行成功率）。"""
    results = getattr(response, "tool_results", None) or []
    return [str(item.get("status", "")) for item in results]


def tools_match(expected: list[str], actual: list[str]) -> bool:
    """期望工具与实际工具按集合比较是否一致；空集合也要正确计分（空集 == 空集为 True）。"""
    return set(expected or []) == set(actual or [])


def _base_completion(question: dict, response: Any, error: str | None) -> tuple[bool, str]:
    """基础完成条件：无异常 + 回答非空 + 无失败标志 + 待确认状态符合预期。"""
    if error is not None:
        return False, f"调用抛出异常：{error}"
    answer = (getattr(response, "answer", "") or "") if response is not None else ""
    if not str(answer).strip():
        return False, "回答为空"
    if "系统未能生成回答" in answer or "处理失败" in answer:
        return False, "回答含失败标志"
    pending = bool(getattr(response, "pending_confirmation", None)) if response is not None else False
    if pending != bool(question["needs_confirmation"]):
        return False, "pending_confirmation 有无与 needs_confirmation 不一致"
    return True, "基础条件满足（非空、无异常、待确认状态符合预期）"


def judge_completion(question: dict, response: Any, error: str | None) -> tuple[bool, str]:
    """按本题 completion_rule 确定性判定任务是否完成，返回 (是否完成, 判定说明)。

    判定规则见模块常量 RULE_DEFINITIONS；全程只读取 ChatResponse 的可观测字段，
    不接受任何人工填写的「完成 / 未完成」标记。
    """
    base_ok, reason = _base_completion(question, response, error)
    if not base_ok:
        return False, reason

    rule = question.get("completion_rule", "answer")
    results = list(getattr(response, "tool_results", None) or []) if response is not None else []
    sources = list(getattr(response, "sources", None) or []) if response is not None else []
    answer = (getattr(response, "answer", "") or "") if response is not None else ""
    pending = getattr(response, "pending_confirmation", None) if response is not None else None

    if rule == "answer":
        extra_ok, extra = True, "无附加条件"
    elif rule == "answer_and_sources":
        extra_ok = len(sources) > 0
        extra = f"知识来源 {len(sources)} 条"
    elif rule == "answer_and_tool_items":
        extra_ok = any(isinstance((item.get("result") or {}).get("items"), list) for item in results)
        extra = "工具结果含 items 列表" if extra_ok else "工具结果缺少 items 列表"
    elif rule == "answer_and_tool_found":
        extra_ok = any("found" in (item.get("result") or {}) for item in results)
        extra = "工具结果含 found 字段" if extra_ok else "工具结果缺少 found 字段"
    elif rule == "answer_and_pending":
        extra_ok = (
            isinstance(pending, dict)
            and isinstance(pending.get("字段"), dict)
            and len(pending["字段"]) > 0
        )
        extra = "已返回非空待确认工单字段" if extra_ok else "未返回有效待确认工单字段"
    elif rule == "answer_and_clarify":
        extra_ok = (any(k in answer for k in ("请提供", "请补充", "还需要")) and not results)
        extra = "信息不足时主动追问且未执行工具" if extra_ok else "未给出追问提示或误执行了工具"
    elif rule == "answer_and_no_answer":
        extra_ok = len(sources) == 0 and ("没有检索到" in answer or "无法据此给出" in answer)
        extra = "无命中且如实拒答" if extra_ok else "未如实拒答（或存在来源命中）"
    else:  # load_questions 已校验，此处仅作兜底
        extra_ok, extra = False, f"未知完成规则 {rule}"

    return bool(extra_ok), f"{reason}；{extra}"


def evaluate_question(
    question: dict, response: Any, error: str | None, elapsed_ms: float
) -> dict:
    """把单题的标注 + 真实响应整理成逐题明细（中文键，供报告与聚合使用）。"""
    expected_tools = list(question.get("expected_tools") or [])
    actual_tools = _extract_tools(response) if response is not None else []
    intent = (getattr(response, "intent", "") or "") if response is not None else ""
    completed, completion_detail = judge_completion(question, response, error)
    pending_expected = bool(question["needs_confirmation"])
    pending_actual = bool(getattr(response, "pending_confirmation", None)) if response is not None else False
    answer = (getattr(response, "answer", "") or "") if response is not None else ""
    summary = re.sub(r"\s+", " ", answer).strip()[:60]

    return {
        "题号": question["id"],
        "类别": question["类别"],
        "问题": question["message"],
        "期望意图": question["expected_intent"],
        "实际意图": intent,
        "意图命中": intent == question["expected_intent"],
        "期望工具": expected_tools,
        "实际工具": actual_tools,
        "工具集合一致": tools_match(expected_tools, actual_tools),
        "工具选择计入分母": len(expected_tools) > 0,
        "工具状态": _tool_statuses(response) if response is not None else [],
        "期望待确认": pending_expected,
        "实际待确认": pending_actual,
        "待确认符合": pending_actual == pending_expected,
        "是否完成": bool(completed),
        "完成规则": question.get("completion_rule", "answer"),
        "完成判定说明": completion_detail,
        "耗时毫秒": round(float(elapsed_ms or 0.0), 2),
        "回答摘要": summary,
        "异常": error,
        # 新字段用 getattr 兼容：主任务正在为 ChatResponse 增加 decision_source / plan_source /
        # fallback，评估不得假设它们一定存在。
        "决策来源": str(getattr(response, "decision_source", "") or "") if response is not None else "",
        "规划来源": str(getattr(response, "plan_source", "") or "") if response is not None else "",
        "是否回退": bool(getattr(response, "fallback", False)) if response is not None else False,
    }


def aggregate_metrics(details: list[dict]) -> dict:
    """根据逐题明细聚合四项指标（纯函数，便于单元测试验证计算边界）。

    边界约定：
    - 工具选择准确率分母为「工具选择计入分母=True」的题数（即 expected_tools 非空）；
      分母为 0 时值为 None 并标注无样本，不臆造 1.0。
    - 工具执行成功率汇总所有题的「工具状态」，整次运行无任何工具调用时值为 None
      且「无样本」=True，绝不填 1.0。
    - 空期望工具题的「工具集合一致」仍按空集相等规则计算，但不计入工具选择准确率。
    """
    total = len(details)
    intent_hit = sum(1 for d in details if d.get("意图命中"))
    intent_value = (intent_hit / total) if total else None

    scored = [d for d in details if d.get("工具选择计入分母")]
    tool_den = len(scored)
    tool_hit = sum(1 for d in scored if d.get("工具集合一致"))
    tool_value = (tool_hit / tool_den) if tool_den else None

    all_status: list[str] = []
    for d in details:
        all_status.extend(d.get("工具状态") or [])
    call_total = len(all_status)
    call_success = sum(1 for s in all_status if s == "成功")
    exec_value = (call_success / call_total) if call_total else None

    completed = sum(1 for d in details if d.get("是否完成"))
    completion_value = (completed / total) if total else None

    return {
        "总题数": total,
        "意图识别准确率": {
            "值": intent_value, "命中": intent_hit, "总题数": total,
        },
        "工具选择准确率": {
            "值": tool_value, "命中": tool_hit, "有期望工具题数": tool_den,
            "无样本": tool_den == 0,
        },
        "工具执行成功率": {
            "值": exec_value, "成功": call_success, "总调用": call_total,
            "无样本": call_total == 0,
        },
        "任务完成率": {
            "值": completion_value, "完成": completed, "总题数": total,
        },
    }


@contextmanager
def _isolated_environment() -> Iterator[dict]:
    """把写入重定向到临时目录并在结束时恢复，保证不污染真实运行库/其它测试。"""
    from backend.core.config import settings
    from backend.database import db as db_module

    tmp = Path(tempfile.mkdtemp(prefix="agent_eval_"))
    saved_db = settings.db_path
    saved_upload = settings.upload_dir
    saved_vector = settings.vector_dir
    saved_initialized = db_module._initialized
    try:
        object.__setattr__(settings, "db_path", tmp / "eval.db")
        object.__setattr__(settings, "upload_dir", tmp / "uploads")
        object.__setattr__(settings, "vector_dir", tmp / "vector_db")
        db_module._initialized = False  # 让 init_database() 在新路径真正建表
        yield {"临时目录": str(tmp)}
    finally:
        object.__setattr__(settings, "db_path", saved_db)
        object.__setattr__(settings, "upload_dir", saved_upload)
        object.__setattr__(settings, "vector_dir", saved_vector)
        db_module._initialized = saved_initialized
        shutil.rmtree(tmp, ignore_errors=True)


def run_agent_evaluation() -> dict:
    """真实运行 Agent 专项评估，返回含指标、逐题明细、运行环境与规则说明的字典。

    逐题真实调用 chat_service.chat()；支持 context（多轮前置消息）；不调用 confirm，
    工单创建类题目只到「待确认」，不会写入工单库。
    """
    from backend.core.config import settings
    from backend.database.db import init_database
    from backend.models.schemas import ChatRequest
    from backend.services import chat_service
    from backend.services.document_service import ensure_sample_documents

    questions = load_questions()
    with _isolated_environment() as env:
        init_database()
        doc_info = ensure_sample_documents()

        details: list[dict] = []
        for question in questions:
            session_id = f"agent_eval::{question['id']}"
            response, error = None, None
            try:
                # 多轮题：先在同一会话内依次发送前置消息，构造真实历史。
                for previous in (question.get("context") or []):
                    chat_service.chat(ChatRequest(message=previous, session_id=session_id))
                # 最后一轮作为本题的判定对象。
                response = chat_service.chat(
                    ChatRequest(message=question["message"], session_id=session_id)
                )
            except Exception as exc:  # 单题异常如实记录，不中断整次评估
                error = f"{type(exc).__name__}: {exc}"
            elapsed = float(getattr(response, "elapsed_ms", 0) or 0) if response is not None else 0.0
            details.append(evaluate_question(question, response, error, elapsed))

        metrics = aggregate_metrics(details)
        decision_source_sample = next(
            (d["决策来源"] for d in details if d.get("决策来源")), "规则决策器（Mock 模式）"
        )
        plan_source_sample = next(
            (d["规划来源"] for d in details if d.get("规划来源")), "规则规划器"
        )
        runtime = {
            "LLM 运行模式": settings.llm_mode,
            "是否 Mock": bool(settings.is_mock),
            "决策器": "Mock 规则决策器（规则决策器 + 规则规划器 + 本地抽取式模拟器）"
            if settings.is_mock else "DeepSeek 结构化输出",
            "意图决策来源（样例）": decision_source_sample,
            "规划来源（样例）": plan_source_sample,
            "Embedding 档位": settings.embedding_mode,
            "DeepSeek Key 已配置": bool(settings.deepseek_api_key),
            "样例文档导入": doc_info,
            "隔离方式": "函数内部把 db_path / upload_dir / vector_dir 重定向到临时目录，结束时恢复并删除（未读写真实运行库）",
            "临时目录": env.get("临时目录", ""),
        }

    return {
        "评估对象": "Agent 专项评估（意图识别 / 工具选择 / 工具执行 / 任务完成）",
        "题数": len(details),
        "数据集路径": str(QUESTION_FILE),
        "运行环境": runtime,
        "指标": metrics,
        "指标说明": dict(METRIC_DEFINITIONS),
        "完成判定规则": dict(RULE_DEFINITIONS),
        "逐题明细": details,
        "结论标注": "本次为 Mock 规则决策器评估结果；真实 DeepSeek 模式下未验证。",
    }
