"""通用渲染组件：知识来源、Agent 执行记录、工具结果、指标卡片。"""
from __future__ import annotations

import streamlit as st


def _location(source: dict) -> str:
    parts = []
    if source.get("section"):
        parts.append(f"章节「{source['section']}」")
    if source.get("page"):
        parts.append(f"第 {source['page']} 页")
    return "，".join(parts) or "未提供章节/页码"


def render_sources(sources: list[dict]) -> None:
    if not sources:
        st.caption("本次回答没有知识来源（可能未检索到相关资料，或该任务不依赖知识库）。")
        return
    for source in sources:
        rank = source.get("rank", "?")
        title = f"来源 {rank}｜《{source.get('doc_name', '未知文档')}》｜分数 {float(source.get('score', 0)):.4f}"
        with st.expander(title, expanded=False):
            st.caption(f"位置：{_location(source)}｜文档编号：{source.get('doc_id', '-')}｜文本块：{source.get('chunk_id', '-')}")
            st.text(source.get("snippet", ""))


def render_trace(trace: list[dict]) -> None:
    if not trace:
        st.caption("没有可展示的执行记录。")
        return
    rows = [
        {
            "阶段": item.get("stage", ""),
            "说明": item.get("detail", ""),
            "工具": item.get("tool") or "-",
            "参数摘要": (item.get("args_summary") or "-")[:100],
            "结果": (item.get("result") or "-")[:120],
            "耗时ms": item.get("elapsed_ms", "-"),
        }
        for item in trace
    ]
    st.dataframe(rows, width="stretch", hide_index=True)


def render_tool_results(results: list[dict]) -> None:
    if not results:
        st.caption("本次任务未调用工具。")
        return
    for item in results:
        status = item.get("status", "未知")
        with st.expander(f"{item.get('label', item.get('tool', '工具'))}｜状态：{status}"):
            payload = item.get("result") or {}
            st.write(payload.get("message", "工具未返回说明文本。"))
            st.caption(f"耗时：{item.get('elapsed_ms', 0)} ms")
            if payload.get("items"):
                st.dataframe(payload["items"], width="stretch", hide_index=True)
            if payload.get("ticket"):
                st.json(payload["ticket"])


def metric_cards(metrics: dict[str, float | int | str | None], columns: int = 4) -> None:
    items = list(metrics.items())
    if not items:
        return
    cols = st.columns(min(columns, len(items)))
    for index, (label, value) in enumerate(items):
        display = "—" if value is None else (f"{value:.4f}" if isinstance(value, float) else str(value))
        with cols[index % len(cols)]:
            st.metric(label, display)
