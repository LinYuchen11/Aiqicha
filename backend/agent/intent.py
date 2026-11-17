"""意图识别：9 类意图；规则决策器 + 真实模型结构化输出双通道。

指代识别通过 resolve_query 把短追问与上一轮问题拼接，实现上下文关联。
"""
from __future__ import annotations

import re

from backend.core.log_utils import get_logger
from backend.llm.client import LLMClient
from backend.rag.prompt import build_intent_prompt

logger = get_logger(__name__)

INTENT_LABELS = {
    "knowledge_query": "企业知识查询",
    "it_consult": "IT 服务咨询",
    "ticket_create": "工单创建",
    "ticket_query": "工单状态查询",
    "multi_step": "多步骤综合任务",
    "multi_tool": "多工具连续任务",
    "chitchat": "普通闲聊",
    "unknown": "无法识别或超出能力",
    "ticket_confirm": "工单确认",
}

_TICKET_NO_RE = re.compile(r"IT-\d{8}-\d{4}", re.IGNORECASE)
_FOLLOWUP_MARKERS = ("那", "呢", "如果", "要是", "换成", "改成", "还有", "再", "它", "这个", "设计软件", "补充")
_IT_KEYWORDS = (
    "网络", "wifi", "无线", "软件", "安装", "账号", "密码", "权限", "打印机", "电脑",
    "故障", "vpn", "邮箱", "驱动", "蓝屏", "无法连接", "连不上", "上不了网", "设计软件",
    "许可证", "it服务", "工单", "报修", "扫描仪",
)
_KNOWLEDGE_KEYWORDS = (
    "制度", "请假", "报销", "考勤", "差旅", "办公用品", "会议室", "采购", "审批",
    "流程", "规定", "如何", "怎么", "多少", "几天", "条件", "标准", "申请", "手册",
    "条款", "工作日", "额度", "时限", "报销单", "年假", "加班", "调休",
)
_CHITCHAT_KEYWORDS = ("你好", "您好", "在吗", "谢谢", "你是谁", "早上好", "下午好", "hi", "hello")


def resolve_query(message: str, history: list[dict]) -> str:
    """短追问结合上一轮用户问题，处理指代与补充条件。"""
    text = (message or "").strip()
    if len(text) <= 24 and any(marker in text for marker in _FOLLOWUP_MARKERS):
        previous = ""
        for item in reversed(history or []):
            if item.get("role") == "user":
                previous = str(item.get("content", "")).strip()
                break
        if previous:
            return f"{previous}；补充条件：{text}"
    return text


def _rule_decision(resolved: str, message: str) -> dict:
    lowered = resolved.lower()
    slots: dict = {}
    ticket_no = _TICKET_NO_RE.search(resolved)
    if ticket_no:
        slots["ticket_no"] = ticket_no.group(0).upper()

    # 多工具连续任务必须优先判定，否则会被 ticket_query 分支拦截
    if "工单" in resolved and any(k in resolved for k in ("先查", "再查", "并查询", "然后查", "同时查询", "顺带查")):
        intent = "multi_tool"
        reason = "一次请求中明确要求连续执行多个不同工具"
    elif any(k in resolved for k in ("如果", "若", "不行", "解决不了", "无法解决", "还是不行")) and any(
        k in resolved for k in ("工单", "报修", "提交")
    ):
        intent = "multi_step"
        reason = "同时包含查询解决办法与条件性创建工单的表述"
    elif "工单" in resolved and any(k in resolved for k in ("状态", "进度", "查询", "查一下", "怎么样", "处理到")):
        intent = "ticket_query"
        reason = "包含工单状态查询意图"
    elif any(k in lowered for k in ("创建工单", "提交工单", "报修", "开个工单", "建个工单", "新建工单", "帮我提工单", "生成工单", "创建 it 工单")):
        intent = "ticket_create"
        reason = "明确提出创建或提交工单"
    elif any(k in lowered for k in _IT_KEYWORDS):
        intent = "it_consult"
        reason = "包含 IT 服务、故障或软件权限相关关键词"
    elif any(k in resolved for k in _KNOWLEDGE_KEYWORDS):
        intent = "knowledge_query"
        reason = "包含企业制度、流程、标准类查询关键词"
    elif len(message.strip()) <= 12 and any(k in lowered for k in _CHITCHAT_KEYWORDS):
        intent = "chitchat"
        reason = "短句问候或闲聊"
    elif any(k in resolved for k in ("吗", "呢", "?", "？", "是否", "有没有", "多少", "怎么",
                                    "如何", "什么", "哪些", "规定", "补贴", "制度", "能不能")):
        # 业务疑问句一律交给 RAG 检索，由检索层判断资料是否充足，
        # 避免把「公司是否有 X 制度」错判为能力之外的请求。
        intent = "knowledge_query"
        reason = "业务疑问句，交由知识库检索判断资料是否充足"
    else:
        intent = "unknown"
        reason = "未匹配到系统支持的任务类型"
    return {"intent": intent, "confidence": 0.85, "reason": reason, "slots": slots}


def classify(message: str, history: list[dict], llm: LLMClient | None = None) -> dict:
    """返回意图、槽位、上下文改写后的查询与决策来源。"""
    client = llm or LLMClient()
    resolved = resolve_query(message, history)
    rule = _rule_decision(resolved, message)
    base = {
        "resolved_query": resolved,
        "source": "规则决策器（Mock 模式）",
        "fallback": False,
    }
    if client.is_mock:
        return {**base, **rule}
    system, user = build_intent_prompt(resolved, history)
    try:
        data = client.complete_json(system, user)
        intent = str(data.get("intent", "")).strip()
        if intent not in INTENT_LABELS:
            raise ValueError("模型返回了未定义的意图")
        slots = dict(rule["slots"])
        for key, value in (data.get("slots") or {}).items():
            if value not in (None, "", []):
                slots[str(key)] = value
        return {
            **base,
            "intent": intent,
            "confidence": float(data.get("confidence", 0.7)),
            "reason": str(data.get("reason", "模型结构化分类")),
            "slots": slots,
            "source": "DeepSeek 结构化输出",
        }
    except Exception as exc:
        logger.warning("模型意图识别失败，回退规则决策器：%s", exc)
        return {**base, **rule, "source": "规则决策器（模型失败回退）", "fallback": True}
