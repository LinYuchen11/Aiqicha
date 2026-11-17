"""页面四：Agent 工具管理。工具清单、参数、真实调用、执行记录与工单列表。"""
from __future__ import annotations

import streamlit as st

from frontend import api_client as api
from frontend.components.render import metric_cards
from frontend.components.style import mock_banner, page_header, section, show_api_error

page_header(
    "Agent 工具管理",
    "Agent 通过工具注册表选择并执行真实 Python 函数；本页可直接调用工具验证参数校验与数据库读写。",
    badge="工具执行层",
)
try:
    mock_banner(bool(api.health().get("是否为模拟运行", True)))
except Exception as exc:
    show_api_error(exc)

section("当前工具列表")
try:
    tools_data = api.tools()
    tool_items = tools_data.get("工具", [])
    stats = tools_data.get("统计", {})
    metric_cards({
        "注册工具数": len(tool_items),
        "累计调用": stats.get("调用总数", 0),
        "成功": stats.get("成功", 0),
        "失败": stats.get("失败", 0),
    })
    for item in tool_items:
        with st.expander(f"{item['label']}（{item['name']}）"):
            st.write(item["description"])
            st.caption(f"需要用户确认：{'是' if item.get('requires_confirmation') else '否'}")
            st.markdown("**参数定义（Pydantic Schema）**")
            st.json(item.get("parameters", {}))
except Exception as exc:
    tool_items = []
    show_api_error(exc)

section("直接调用工具")
if tool_items:
    name = st.selectbox("选择工具", [item["name"] for item in tool_items],
                        format_func=lambda x: next((i["label"] for i in tool_items if i["name"] == x), x))
    args: dict = {}
    if name == "it_service_query":
        args["keyword"] = st.text_input("查询关键词", "软件安装")
        category = st.selectbox("服务类别（可选）", ["", "软件安装", "账号权限", "网络故障", "办公设备", "行政事务"])
        if category:
            args["category"] = category
    elif name == "ticket_query":
        args["ticket_no"] = st.text_input("工单编号", placeholder="IT-20261116-0001")
    elif name == "ticket_create":
        args["fault_type"] = st.text_input("故障类型", "网络故障")
        args["description"] = st.text_area("故障描述", "办公电脑无法连接公司无线网络，重启后仍未恢复。")
        args["contact"] = st.text_input("联系方式（必须由用户提供）", "内线 8000")
        args["department"] = st.text_input("所属部门（可选）", "")
        args["urgency"] = st.selectbox("紧急程度", ["普通", "紧急"])
        args["confirmed"] = st.checkbox("我已确认创建该工单（不勾选将拒绝写库）", value=False)
    if st.button("执行工具", type="primary"):
        try:
            outcome = api.invoke_tool(name, args)
            st.success(f"执行状态：{outcome.get('status')}｜耗时 {outcome.get('elapsed_ms')} ms")
            payload = outcome.get("result") or {}
            st.write(payload.get("message", ""))
            if payload.get("items"):
                st.dataframe(payload["items"], width="stretch", hide_index=True)
            if payload.get("ticket"):
                st.json(payload["ticket"])
        except Exception as exc:
            show_api_error(exc)
else:
    st.info("工具列表加载失败，请检查后端服务。")

section("工具调用记录")
try:
    logs = api.tool_logs(limit=100).get("记录", [])
    if logs:
        st.dataframe(
            [
                {
                    "时间": item["created_at"], "工具": item["tool_name"],
                    "状态": item["status"], "参数": str(item.get("args_json", {}))[:90],
                    "结果": str(item.get("result_json") or {})[:90],
                    "耗时ms": item["elapsed_ms"], "错误": item.get("error_msg") or "-",
                }
                for item in logs
            ],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("暂无工具调用记录。")
except Exception as exc:
    show_api_error(exc)

section("已创建工单")
try:
    tickets = api.tickets().get("工单", [])
    if tickets:
        st.dataframe(
            [
                {
                    "工单编号": item["ticket_no"], "故障类型": item["fault_type"],
                    "状态": item["status"], "紧急程度": item["urgency"],
                    "联系方式": item["contact"], "创建时间": item["created_at"],
                    "处理说明": item["handling_note"],
                }
                for item in tickets
            ],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("数据库中暂无工单。可通过智能助手或上方工具调用创建。")
except Exception as exc:
    show_api_error(exc)
