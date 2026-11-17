"""工具一：企业 IT 服务查询。读取 SQLite 中的模拟服务目录并返回真实查询结果。"""
from __future__ import annotations

from backend.database.ticket_repo import list_it_services
from backend.tools.schemas import ITServiceQueryArgs


def query_it_service(args: ITServiceQueryArgs) -> dict:
    items = list_it_services(category=args.category, keyword=args.keyword)
    if not items:
        return {
            "found": False,
            "count": 0,
            "items": [],
            "message": "未查询到匹配的 IT 服务条目。可尝试更换关键词，或提交 IT 服务工单咨询（模拟数据）。",
        }
    lines = [
        f"- {item['name']}（{item['category']}）：{item['description']} "
        f"支持状态：{'支持' if item['supported'] else '需审批/受限'}；"
        f"办理渠道：{item['apply_channel']}；时效：{item['sla']}"
        for item in items
    ]
    return {
        "found": True,
        "count": len(items),
        "items": items,
        "message": "查询到以下 IT 服务条目（模拟数据）：\n" + "\n".join(lines),
    }
