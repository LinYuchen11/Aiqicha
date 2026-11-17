"""工具二/三：IT 工单创建与状态查询，以及创建前的待确认单构造。

工单创建强制要求用户确认（confirmed=True），所有字段均由用户提供或从对话中抽取，
不会臆测身份、部门、联系方式。
"""
from __future__ import annotations

import re

from backend.core.errors import ToolError
from backend.database.ticket_repo import create_ticket, get_ticket
from backend.tools.schemas import TicketCreateArgs, TicketQueryArgs

_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_CONTACT_HINT_RE = re.compile(r"(?:联系方式|联系人|电话|手机|邮箱)[:：为是]?\s*([^\s，,。；;]{2,80})")
_FAULT_KEYWORDS = (
    ("网络故障", ("网络", "wifi", "无线", "上不了网", "无法连接", "vpn", "断网")),
    ("账号权限", ("账号", "权限", "密码", "邮箱", "登录", "认证", "vpn账号")),
    ("软件安装", ("软件", "安装", "许可证", "设计软件", "photoshop", "autocad", "figma")),
    ("办公设备", ("打印机", "扫描仪", "电脑", "笔记本", "显示器", "卡纸", "设备")),
    ("行政事务", ("会议室", "办公用品", "预约")),
)


def guess_fault_type(text: str) -> str:
    lowered = (text or "").lower()
    for fault_type, keywords in _FAULT_KEYWORDS:
        if any(word in lowered for word in keywords):
            return fault_type
    return "其他 IT 故障"


def _extract_contact(text: str) -> str:
    phone = _PHONE_RE.search(text or "")
    if phone:
        return phone.group(0)
    email = _EMAIL_RE.search(text or "")
    if email:
        return email.group(0)
    hint = _CONTACT_HINT_RE.search(text or "")
    if hint:
        return hint.group(1).strip()
    return ""


def build_ticket_draft(message: str, slots: dict | None = None, history: list[dict] | None = None) -> dict:
    """生成待确认单。返回缺失字段清单，供 Agent 主动追问；此函数不写数据库。"""
    slots = slots or {}
    # 追问补答轮：故障信息在上一轮用户消息里，联系方式在本轮；
    # 只取上一轮用户文本（排除助手回答），并避免与已合并的 message 重复。
    previous = [
        str(h.get("content", "")) for h in (history or []) if h.get("role") == "user"
    ]
    context = "\n".join(text for text in previous if text and text not in message)
    combined = f"{context}\n{message}".strip() if context else message
    contact = str(slots.get("contact") or _extract_contact(combined) or "").strip()
    draft = {
        "fault_type": str(slots.get("fault_type") or guess_fault_type(combined)).strip(),
        "description": str(slots.get("description") or combined).strip()[:1000],
        "contact": contact,
        "department": str(slots.get("department") or "").strip(),
        "urgency": str(slots.get("urgency") or ("紧急" if "紧急" in combined or "加急" in combined else "普通")),
    }
    missing = []
    if len(draft["description"]) < 5:
        missing.append("故障描述（请说明具体现象，例如哪台设备、出现什么报错）")
    if not contact:
        missing.append("联系方式（手机号或企业邮箱，系统不会替你假设）")
    return {"draft": draft, "missing": missing, "complete": not missing}


def create_ticket_tool(args: TicketCreateArgs) -> dict:
    if not args.confirmed:
        raise ToolError(
            "创建工单前必须由用户确认",
            "请先在界面上确认待提交工单信息，确认后才会写入数据库",
        )
    row = create_ticket(
        fault_type=args.fault_type,
        description=args.description,
        contact=args.contact,
        department=args.department,
        urgency=args.urgency,
        session_id=args.session_id,
    )
    return {
        "found": True,
        "ticket_no": row["ticket_no"],
        "ticket": row,
        "message": (
            f"工单已创建：{row['ticket_no']}｜类型：{row['fault_type']}｜"
            f"状态：{row['status']}｜提交时间：{row['created_at']}"
        ),
    }


def query_ticket_tool(args: TicketQueryArgs) -> dict:
    row = get_ticket(args.ticket_no)
    if not row:
        return {
            "found": False,
            "message": f"未查询到工单 {args.ticket_no}，请核对编号后重试。",
        }
    return {
        "found": True,
        "ticket": row,
        "message": (
            f"工单 {row['ticket_no']}｜类型：{row['fault_type']}｜状态：{row['status']}｜"
            f"创建时间：{row['created_at']}｜处理说明：{row['handling_note']}"
        ),
    }
