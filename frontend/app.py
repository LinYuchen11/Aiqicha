"""Streamlit 入口：中文导航、系统状态与 Mock 模式显著提示。"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend import api_client as api  # noqa: E402
from frontend.components.style import inject_style  # noqa: E402

st.set_page_config(
    page_title="企业智能知识助手",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_style()

with st.sidebar:
    st.markdown("### ✦ 企业智能知识助手")
    st.caption("通用企业级智能知识管理与任务助手｜RAG + LangGraph Agent")
    st.divider()
    try:
        info = api.health()
        if info.get("是否为模拟运行"):
            st.warning(
                "**当前为 Mock 模拟运行**\n\n未配置 DeepSeek API Key。"
                "答案由本地抽取式模拟器基于真实检索片段生成，不是大模型输出。"
            )
        else:
            st.success("**当前为 DeepSeek 真实模型运行**")
        llm = info.get("大模型", {})
        st.caption(f"大模型实际档位：{llm.get('模式', '-')}｜模型：{llm.get('模型', '-')}")
        emb = info.get("向量方案", {})
        st.caption(
            f"Embedding：{emb.get('模型名称', '-')}｜{emb.get('向量维度', '-')} 维"
            f"｜配置 {emb.get('配置档位', '-')} / 实际 {emb.get('实际档位', '-')}"
        )
        if not emb.get("是否语义向量", False):
            st.caption(
                "⚠️ 当前为词面哈希向量（非语义 Embedding），仅作离线备用；"
                "正式演示推荐 local / BAAI/bge-small-zh-v1.5"
            )
        compat = info.get("向量库一致性", {})
        if not compat.get("是否一致", True):
            st.error(f"向量库模型不一致：{compat.get('提示', '')}，请执行重建脚本。")
        doc_stats = info.get("文档统计", {})
        st.caption(f"向量库：{info.get('向量库', '-')}｜向量数：{info.get('向量数量', 0)}")
        st.caption(f"文档：{doc_stats.get('文档总数', 0)} 份｜文本块：{doc_stats.get('文本块总数', 0)} 个")
    except Exception as exc:
        st.error(f"后端未就绪：{getattr(exc, 'message', exc)}")
        st.caption("请先启动后端服务，再刷新本页面。")
    st.divider()
    st.caption("全部页面均真实调用 FastAPI 接口")

pages = {
    "工作台": [
        st.Page("pages/assistant.py", title="智能助手", icon="💬", default=True),
    ],
    "知识与检索": [
        st.Page("pages/knowledge.py", title="知识库管理", icon="📚"),
        st.Page("pages/retrieval.py", title="检索调试", icon="🔍"),
    ],
    "Agent 与评估": [
        st.Page("pages/tools.py", title="Agent 工具管理", icon="🧩"),
        st.Page("pages/evaluation.py", title="RAG 评估中心", icon="📊"),
    ],
}

navigation = st.navigation(pages)
navigation.run()
