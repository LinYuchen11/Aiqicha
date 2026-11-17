"""页面一：智能助手。连续对话、知识来源、Agent 执行记录、工具结果与工单确认。"""
from __future__ import annotations

import streamlit as st

from frontend import api_client as api
from frontend.components.render import render_sources, render_tool_results, render_trace
from frontend.components.style import mock_banner, page_header, section, show_api_error


def _current_session() -> str:
    if "eka_session_id" not in st.session_state:
        try:
            items = api.sessions().get("会话") or []
            st.session_state.eka_session_id = (
                items[0]["session_id"] if items else api.new_session()["会话"]["session_id"]
            )
        except Exception:
            st.session_state.eka_session_id = ""
    return st.session_state.eka_session_id


def _sidebar(sid: str) -> None:
    with st.sidebar:
        st.markdown("#### 会话管理")
        if st.button("＋ 新建对话", width="stretch"):
            try:
                st.session_state.eka_session_id = api.new_session()["会话"]["session_id"]
                st.rerun()
            except Exception as exc:
                show_api_error(exc)
        try:
            items = api.sessions().get("会话") or []
            labels = {
                f"{item['title'][:20]}（{item['message_count']} 条）": item["session_id"]
                for item in items
            }
            options = list(labels)
            index = next((i for i, key in enumerate(options) if labels[key] == sid), 0) if options else 0
            selected = st.selectbox("历史对话", options or ["暂无会话"], index=index)
            if selected in labels and labels[selected] != sid:
                st.session_state.eka_session_id = labels[selected]
                st.rerun()
        except Exception as exc:
            st.caption(f"会话列表加载失败：{getattr(exc, 'message', exc)}")
        if sid and st.button("重置当前对话", width="stretch"):
            try:
                api.reset_session(sid)
                st.rerun()
            except Exception as exc:
                show_api_error(exc)


page_header(
    "智能助手",
    "用自然语言查询企业制度、咨询 IT 服务，或让 Agent 帮你创建与查询工单；回答下方附带真实来源与执行记录。",
    badge="LangGraph Agent",
)
try:
    health = api.health()
    mock_banner(bool(health.get("是否为模拟运行", True)))
except Exception as exc:
    health = {}
    show_api_error(exc)

sid = _current_session()
_sidebar(sid)

with st.expander("检索与工作流参数", expanded=False):
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        top_k = st.slider("Top-K 召回数", 1, 15, 5)
    with col_b:
        mode = st.selectbox("检索方式", ["hybrid", "vector", "keyword"],
                            format_func=lambda x: {"hybrid": "混合检索", "vector": "纯向量检索", "keyword": "关键词检索"}[x])
    with col_c:
        weight = st.slider("向量权重", 0.0, 1.0, 0.6, 0.05)
    with col_d:
        use_rerank = st.checkbox("启用重排序", value=False)
    st.caption("混合检索最终得分 = 向量权重 × 向量分 + (1 − 向量权重) × 关键词分；重排序默认使用可解释的规则式方法。")

section("对话记录")
try:
    history = api.messages(sid).get("消息", []) if sid else []
except Exception as exc:
    history = []
    show_api_error(exc)

for message in history:
    role = "user" if message.get("role") == "user" else "assistant"
    with st.chat_message(role):
        st.markdown(message.get("content", ""))
        if role == "assistant":
            with st.expander("知识来源", expanded=False):
                render_sources(message.get("sources") or [])
            with st.expander("Agent 执行记录", expanded=False):
                render_trace(message.get("trace") or [])
            with st.expander("工具调用结果", expanded=False):
                render_tool_results(message.get("tool_results") or [])

section("待确认工单")
try:
    draft = api.pending(sid).get("待确认工单") if sid else None
except Exception:
    draft = None
if draft:
    st.info("以下工单尚未写入数据库。请核对信息后确认，或取消。")
    st.json(draft)
    edited_contact = st.text_input("如需修改联系方式，请在此填写", value=str(draft.get("contact", "") or ""))
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("确认创建", type="primary", width="stretch"):
            try:
                api.confirm({"session_id": sid, "confirm": True, "edits": {"contact": edited_contact}})
                st.success("工单已提交并写入数据库。")
                st.rerun()
            except Exception as exc:
                show_api_error(exc)
    with cancel_col:
        if st.button("取消创建", width="stretch"):
            try:
                api.confirm({"session_id": sid, "confirm": False})
                st.info("已取消，未写入任何数据。")
                st.rerun()
            except Exception as exc:
                show_api_error(exc)
else:
    st.caption("当前没有待确认的工单。")

prompt = st.chat_input("请输入问题或任务，例如：年假怎么申请？／帮我查询工单 IT-20261116-0001")
if prompt:
    if not sid:
        st.error("会话未就绪，请先启动后端服务并刷新页面。")
    else:
        with st.spinner("Agent 正在执行工作流…"):
            try:
                api.chat({
                    "session_id": sid, "message": prompt, "top_k": top_k,
                    "retrieval_mode": mode, "hybrid_weight": weight, "use_rerank": use_rerank,
                })
                st.rerun()
            except Exception as exc:
                show_api_error(exc)
