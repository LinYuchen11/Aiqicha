"""LangGraph 节点实现。每个节点只做一件事，并把真实执行记录写入 trace。

trace 不展示模型思维链，只记录实际发生的、可验证的系统动作。
"""
from __future__ import annotations

import json
import re
import time

from backend.agent.intent import INTENT_LABELS, classify
from backend.agent.planner import plan_steps
from backend.agent.tool_guard import sanitize_tool_results
from backend.core.errors import ToolError
from backend.database.conversation_repo import get_pending, set_pending
from backend.llm.client import LLMClient
from backend.llm.mock import chitchat_answer, unknown_answer
from backend.rag.pipeline import RAGPipeline
from backend.tools import build_ticket_draft, invoke, list_tool_infos

_TICKET_NO_RE = re.compile(r"IT-\d{8}-\d{4}", re.IGNORECASE)
_IT_TOPIC_WORDS = ("网络", "软件", "账号", "权限", "打印机", "VPN", "邮箱", "电脑", "安装", "密码", "故障")


def _trace(
    state: dict, stage: str, detail: str, *, tool: str | None = None,
    args_summary: str | None = None, result: str | None = None,
    elapsed_ms: float | None = None, decision_source: str | None = None,
) -> list[dict]:
    entry: dict = {"stage": stage, "detail": detail}
    if tool is not None:
        entry["tool"] = tool
    if args_summary is not None:
        entry["args_summary"] = args_summary
    if result is not None:
        entry["result"] = result
    if elapsed_ms is not None:
        entry["elapsed_ms"] = round(elapsed_ms, 2)
    if decision_source is not None:
        entry["decision_source"] = decision_source
    return [*(state.get("trace") or []), entry]


_SUPPLEMENT_RE = re.compile(r"1[3-9]\d{9}|补充|联系方式|电话|手机|邮箱")


def _is_supplement(message: str) -> bool:
    """判断本轮是否是对上一轮工单追问的补充回答。"""
    text = (message or "").strip()
    if _SUPPLEMENT_RE.search(text):
        return True
    return len(text) <= 20 and not any(k in text for k in ("?", "？", "吗", "如何", "怎么", "多少"))


def _it_keyword(message: str) -> str:
    for word in _IT_TOPIC_WORDS:
        if word.lower() in message.lower():
            return word
    return message.strip()[:20]


def intent_node(state: dict) -> dict:
    if state.get("action") == "confirm":
        return {
            "intent": "ticket_confirm",
            "intent_label": INTENT_LABELS["ticket_confirm"],
            "intent_source": "用户确认动作",
            "decision_source": "用户确认动作（非模型决策）",
            "plan_source": "规则规划器",
            "fallback": False,
            "slots": {},
            "resolved_query": state.get("message", ""),
            "trace": _trace(
                state, "意图识别", "识别为「工单确认」：用户提交了待确认工单的处理结果",
                decision_source="用户确认动作（非模型决策）",
            ),
        }

    # 上一轮处于工单创建追问状态，且本轮是纯补充信息 → 恢复挂起意图，避免被判成 unknown
    if state.get("pending_intent") == "ticket_create" and _is_supplement(state.get("message", "")):
        previous = ""
        for item in reversed(state.get("history") or []):
            if item.get("role") == "user":
                previous = str(item.get("content", "")).strip()
                break
        merged = f"{previous}；补充信息：{state['message']}" if previous else state["message"]
        source = "规则决策器（挂起意图恢复）"
        return {
            "intent": "ticket_create",
            "intent_label": INTENT_LABELS["ticket_create"],
            "intent_source": source,
            "decision_source": source,
            "fallback": False,
            "slots": {},
            "message": merged,
            "resolved_query": merged,
            "trace": _trace(
                state, "意图识别", "检测到上一轮工单信息追问的补充回答，恢复「工单创建」意图",
                result=merged[:120], decision_source=source,
            ),
        }

    result = classify(state["message"], state.get("history") or [], LLMClient())
    label = INTENT_LABELS.get(result["intent"], "未知")
    detail = f"识别为「{label}」（{result['source']}）：{result['reason']}"
    if result.get("resolved_query") != state["message"]:
        detail += f"；上下文改写：{result['resolved_query']}"
    return {
        "intent": result["intent"],
        "intent_label": label,
        "intent_source": result["source"],
        "decision_source": result["source"],
        "fallback": bool(result.get("fallback")),
        "slots": result.get("slots") or {},
        "resolved_query": result["resolved_query"],
        "trace": _trace(
            state, "意图识别", detail, result=f"置信度 {result.get('confidence', 0):.2f}",
            decision_source=result["source"],
        ),
    }


def planner_node(state: dict) -> dict:
    info = plan_steps(
        state.get("intent", "unknown"), state.get("message", ""),
        state.get("slots") or {}, LLMClient(),
    )
    return {
        "plan": info["steps"],
        "route": info["route"],
        "plan_source": info["source"],
        "fallback": bool(state.get("fallback")) or info["fallback"],
        "needs_clarification": info["needs_clarification"],
        "clarifying_question": info["clarifying_question"],
        "trace": _trace(
            state, "任务规划",
            f"执行路径：{info['route']}；步骤：" + " → ".join(info["steps"]),
            result=info["source"], decision_source=info["source"],
        ),
    }


def tool_select_node(state: dict) -> dict:
    """按意图 + 工具注册表选择工具；这一步不使用模型，保证可解释与可解耦。"""
    intent = state.get("intent")
    available = {info.name for info in list_tool_infos()}
    if intent == "multi_tool":
        # 多工具连续执行：按 plan_index 取队列中的下一个工具
        index = int(state.get("plan_index") or 0)
        if index == 0:
            name = "it_service_query"
            args = {"keyword": _it_keyword(state.get("resolved_query") or state.get("message", ""))}
            missing, question = False, ""
        elif index == 1:
            name = "ticket_query"
            slots = state.get("slots") or {}
            found = slots.get("ticket_no") or _TICKET_NO_RE.search(state.get("message", ""))
            ticket_no = str(found.group(0)).upper() if hasattr(found, "group") else str(found or "").upper()
            args = {"ticket_no": ticket_no} if ticket_no else {}
            missing = not ticket_no
            question = "请提供要查询的工单编号（格式如 IT-20261116-0001），我再继续第二步查询。" if missing else ""
        else:
            return {
                "selected_tool": None, "tool_args": {}, "needs_clarification": False,
                "trace": _trace(state, "工具选择", "多工具队列已执行完毕", result="连续工具执行结束"),
            }
    elif intent == "ticket_query":
        name = "ticket_query"
        slots = state.get("slots") or {}
        found = slots.get("ticket_no") or _TICKET_NO_RE.search(state.get("message", ""))
        ticket_no = str(found.group(0)).upper() if hasattr(found, "group") else str(found or "").upper()
        args = {"ticket_no": ticket_no} if ticket_no else {}
        missing = not ticket_no
        question = "请提供要查询的工单编号（格式如 IT-20261116-0001），我再为你查询。" if missing else ""
    elif intent == "it_consult":
        name = "it_service_query"
        args = {"keyword": _it_keyword(state.get("resolved_query") or state.get("message", ""))}
        missing, question = False, ""
    else:
        return {
            "selected_tool": None, "tool_args": {}, "needs_clarification": False,
            "trace": _trace(state, "工具选择", "当前意图无需调用工具"),
        }
    if name not in available:
        return {
            "selected_tool": None, "tool_args": {}, "needs_clarification": False,
            "errors": [*(state.get("errors") or []), f"工具 {name} 未注册"],
            "trace": _trace(state, "工具选择", f"工具 {name} 未在注册表中，已跳过"),
        }
    return {
        "selected_tool": name,
        "tool_args": args,
        "needs_clarification": missing,
        "clarifying_question": question,
        "trace": _trace(
            state, "工具选择", f"选择工具：{name}",
            tool=name, args_summary=json.dumps(args, ensure_ascii=False)[:160],
            result="缺少必要参数，需向用户追问" if missing else "参数已就绪",
        ),
    }


def tool_execute_node(state: dict) -> dict:
    name = state.get("selected_tool")
    if not name or state.get("needs_clarification"):
        return {
            "tool_results": state.get("tool_results") or [],
            "trace": _trace(state, "工具执行", "参数不足，未执行任何工具", result=state.get("clarifying_question", "")),
        }
    args = dict(state.get("tool_args") or {})
    try:
        outcome = invoke(name, args, state.get("session_id"))
        results = [*(state.get("tool_results") or []), outcome]
        return {
            "tool_results": results,
            # 计划游标前移，供条件边判断「是否还有下一步工具」
            "plan_index": int(state.get("plan_index") or 0) + 1,
            "trace": _trace(
                state, "工具执行", f"工具 {name} 执行{outcome['status']}",
                tool=name,
                args_summary=json.dumps(args, ensure_ascii=False)[:160],
                result=str(outcome["result"].get("message", ""))[:200],
                elapsed_ms=outcome["elapsed_ms"],
            ),
        }
    except ToolError as exc:
        failed = {"tool": name, "label": name, "status": "失败", "result": {"message": exc.message}, "elapsed_ms": 0}
        return {
            "tool_results": [*(state.get("tool_results") or []), failed],
            "plan_index": int(state.get("plan_index") or 0) + 1,
            "errors": [*(state.get("errors") or []), exc.message],
            "trace": _trace(state, "工具执行", f"工具 {name} 执行失败：{exc.message}", tool=name, result=exc.detail[:200]),
        }


def retrieve_node(state: dict) -> dict:
    pipeline = RAGPipeline()
    started = time.perf_counter()
    outcome = pipeline.retrieve(
        query=state.get("resolved_query") or state.get("message", ""),
        top_k=state.get("top_k", 5),
        mode=state.get("retrieval_mode", "hybrid"),
        hybrid_weight=state.get("hybrid_weight"),
        rerank=state.get("use_rerank", False),
    )
    return {
        "outcome": outcome,
        "trace": _trace(
            state, "知识检索",
            f"检索方式：{state.get('retrieval_mode', 'hybrid')}，Top-{state.get('top_k', 5)}，"
            f"召回 {len(outcome.hits)} 个文本块",
            result=outcome.message,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        ),
    }


def collect_info_node(state: dict) -> dict:
    """工单信息收集：只抽取用户已提供的信息，缺项主动追问，不擅自写库。"""
    # 真实模型规划判定「需要追问」时，直接输出追问，不误生成工单草稿
    if state.get("clarifying_question") and state.get("intent") != "ticket_create":
        question = state["clarifying_question"]
        return {
            "needs_clarification": True,
            "clarifying_question": question,
            "pending_confirmation": None,
            "trace": _trace(
                state, "信息收集", "任务规划判定信息不足，需向用户追问",
                result=question[:160], decision_source=state.get("plan_source"),
            ),
        }
    info = build_ticket_draft(
        state.get("message", ""), state.get("slots") or {}, state.get("history") or []
    )
    if not info["complete"]:
        question = (
            "为了创建 IT 服务工单，还需要你补充以下信息：\n"
            + "\n".join(f"- {item}" for item in info["missing"])
            + "\n\n请直接回复这些信息。系统不会替你假设身份、部门或联系方式。"
        )
        # 记录挂起意图：下一轮用户只补充联系方式时，能恢复到「工单创建」而不是被判成 unknown
        set_pending(state["session_id"], None, "ticket_create")
        return {
            "needs_clarification": True,
            "clarifying_question": question,
            "pending_confirmation": None,
            "trace": _trace(state, "信息收集", "工单必要信息不完整，需向用户追问", result="；".join(info["missing"])),
        }
    draft = info["draft"]
    set_pending(state["session_id"], draft, "ticket_create")
    summary = "；".join(f"{k}={v}" for k, v in draft.items() if v)
    return {
        "needs_clarification": False,
        "pending_confirmation": {
            "类型": "工单创建",
            "字段": draft,
            "提示": "请核对以上信息，确认后才会写入数据库；你也可以取消。",
        },
        "trace": _trace(state, "信息收集", "已生成待确认工单，尚未写入数据库", args_summary=summary[:200], result="等待用户确认"),
    }


def confirm_node(state: dict) -> dict:
    """确认分支：用户确认后才调用真实工单创建工具。"""
    draft = get_pending(state["session_id"])
    if not draft:
        return {
            "answer": "当前没有待确认的工单，可能已提交或已被重置。请重新描述你的需求。",
            "pending_confirmation": None,
            "trace": _trace(state, "工单确认", "未找到待确认工单", result="未执行写库操作"),
        }
    if not state.get("confirm"):
        set_pending(state["session_id"], None, None)
        return {
            "answer": "已取消本次工单创建，未向数据库写入任何数据。",
            "pending_confirmation": None,
            "trace": _trace(state, "工单确认", "用户取消，未执行工具", result="已清除待确认状态"),
        }
    merged = dict(draft)
    for key, value in (state.get("edits") or {}).items():
        if key in merged and value not in (None, ""):
            merged[key] = value
    merged["confirmed"] = True
    merged["session_id"] = state["session_id"]
    try:
        outcome = invoke("ticket_create", merged, state["session_id"])
    except ToolError as exc:
        return {
            "answer": f"工单创建失败：{exc.message}。{exc.detail}",
            "errors": [*(state.get("errors") or []), exc.message],
            "trace": _trace(state, "工单确认", f"工单创建工具失败：{exc.message}", tool="ticket_create", result=exc.detail[:200]),
        }
    set_pending(state["session_id"], None, None)
    message = outcome["result"]["message"]
    return {
        "tool_results": [*(state.get("tool_results") or []), outcome],
        "answer": f"已确认并成功创建工单。\n\n{message}\n\n可通过「工单状态查询」随时查看处理进度。",
        "pending_confirmation": None,
        "trace": _trace(
            state, "工单确认", "用户确认后调用工单创建工具", tool="ticket_create",
            args_summary=json.dumps({k: v for k, v in merged.items() if k != "session_id"}, ensure_ascii=False)[:200],
            result=message[:200], elapsed_ms=outcome["elapsed_ms"],
        ),
    }


def multi_step_node(state: dict) -> dict:
    outcome = state.get("outcome")
    if outcome and outcome.hits and outcome.hits[0].score >= 0.08:
        note = (
            "【多步骤任务后续建议】已检索到相关处理办法，请先按上文的资料原文逐步尝试。"
            "若按步骤仍无法解决，请回复「帮我创建工单」并提供联系方式；"
            "我会先生成待确认单，在你确认后才会提交，不会擅自创建。"
        )
    else:
        note = (
            "【多步骤任务后续建议】知识库中没有检索到明确的处理办法。"
            "建议直接创建 IT 服务工单：请回复「帮我创建工单」并提供联系方式。"
        )
    return {
        "multi_step_note": note,
        "trace": _trace(state, "多步骤判定", "根据检索结果决定是否建议创建工单", result=note[:160]),
    }


def integrate_node(state: dict) -> dict:
    intent = state.get("intent", "unknown")
    pipeline = RAGPipeline()
    history = state.get("history") or []
    query = state.get("resolved_query") or state.get("message", "")
    sources: list[dict] = []
    llm_mode = pipeline.llm.mode
    # 运行时来源校验：剔除任何不是由工具注册表真实执行产生的「结果」
    tool_results, dropped = sanitize_tool_results(state.get("tool_results") or [])

    if intent == "multi_tool":
        lines = [f"本次连续执行 {len(tool_results)} 个工具（均由工具注册表真实执行）："]
        for index, result in enumerate(tool_results, start=1):
            payload = result.get("result") or {}
            lines.append(
                f"{index}. {result['tool']}｜{result['status']}｜"
                f"{str(payload.get('message', ''))[:180]}"
            )
        answer = "【多工具连续执行结果】\n" + "\n".join(lines)
        if state.get("needs_clarification") and state.get("clarifying_question"):
            answer += "\n\n" + state["clarifying_question"]
    elif intent in ("knowledge_query", "it_consult", "multi_step"):
        outcome = state.get("outcome") or pipeline.retrieve(
            query, top_k=state.get("top_k", 5), mode=state.get("retrieval_mode", "hybrid")
        )
        answer, llm_mode = pipeline.generate(query, outcome, history)
        sources = [item.model_dump() for item in pipeline.to_sources(outcome)]
        if intent == "multi_step" and state.get("multi_step_note"):
            answer += "\n\n" + state["multi_step_note"]
        if intent == "it_consult":
            lines = []
            for result in tool_results:
                payload = result.get("result") or {}
                for item in payload.get("items") or []:
                    lines.append(
                        f"- {item['name']}（{item['category']}）：办理渠道 {item['apply_channel']}，"
                        f"时效 {item['sla']}，支持状态 {'支持' if item['supported'] else '需审批/受限'}"
                    )
            if lines:
                answer += "\n\n【IT 服务目录查询结果（工具真实执行，模拟数据）】\n" + "\n".join(lines)
    elif intent == "ticket_create":
        if state.get("needs_clarification"):
            answer = state.get("clarifying_question") or "请补充工单必要信息。"
        else:
            draft = (state.get("pending_confirmation") or {}).get("字段") or {}
            answer = (
                "已根据你提供的信息整理出待确认工单：\n\n"
                + "\n".join(f"- {key}：{value}" for key, value in draft.items())
                + "\n\n请在下方点击「确认创建」提交，或点击「取消」。确认前不会写入数据库。"
            )
    elif intent == "ticket_query":
        results = tool_results
        if not results:
            answer = state.get("clarifying_question") or "请提供工单编号后再查询。"
        else:
            payload = results[-1].get("result") or {}
            if not payload.get("found"):
                answer = payload.get("message") or "未查询到该工单。"
            else:
                ticket = payload["ticket"]
                answer = (
                    "工单状态查询结果（来自真实工具执行）：\n\n"
                    f"- 工单编号：{ticket['ticket_no']}\n"
                    f"- 故障类型：{ticket['fault_type']}\n"
                    f"- 当前状态：{ticket['status']}\n"
                    f"- 创建时间：{ticket['created_at']}\n"
                    f"- 处理说明：{ticket['handling_note']}"
                )
    elif intent == "ticket_confirm":
        answer = state.get("answer") or "工单确认流程已完成。"
    elif intent == "chitchat":
        answer = (
            chitchat_answer(state.get("message", ""), INTENT_LABELS["chitchat"])
            if pipeline.llm.is_mock
            else "你好，我是企业智能知识助手，可以帮你查询企业制度与 IT 服务规范、创建或查询工单。请描述具体问题。"
        )
    else:
        answer = unknown_answer() if pipeline.llm.is_mock else "暂时无法识别该请求，或请求超出本系统能力范围。本系统仅支持企业知识查询、IT 服务咨询与工单相关操作。"

    # 模型/工具判定信息不足时，追问优先于常规答案（工单创建分支已自行处理）
    if (
        state.get("needs_clarification") and state.get("clarifying_question")
        and intent != "ticket_create" and intent != "multi_tool"
    ):
        answer = state["clarifying_question"]
    detail = f"整合检索资料与工具结果，生成最终回答（{llm_mode}）"
    if dropped:
        detail += f"；已丢弃 {dropped} 条来源不合法的工具结果"
    return {
        "answer": answer,
        "sources": sources,
        "llm_mode": llm_mode,
        "tool_results": tool_results,
        "trace": _trace(state, "结果整合", detail, result=answer[:160]),
    }


def final_node(state: dict) -> dict:
    started = state.get("started_at") or time.perf_counter()
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    return {
        "elapsed_ms": elapsed,
        "trace": _trace(
            state, "最终回答", f"工作流执行完成，总耗时 {elapsed} ms",
            result=(state.get("answer") or "")[:160], elapsed_ms=elapsed,
        ),
    }
