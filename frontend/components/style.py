"""统一视觉样式：浅色企业级 SaaS 风格，全中文界面元素。"""
from __future__ import annotations

import streamlit as st

CSS = """
<style>
:root{
  --eka-primary:#185FA5; --eka-primary-soft:#E6F1FB; --eka-bg:#F6F8FC;
  --eka-card:#FFFFFF; --eka-border:#E3E9F2; --eka-text:#1F2937;
  --eka-muted:#667085; --eka-success:#0F6E56; --eka-warn:#854F0B;
}
.stApp{background:var(--eka-bg);}
.block-container{max-width:1240px;padding-top:1.6rem;padding-bottom:3rem;}
[data-testid="stSidebar"]{background:#FFFFFF;border-right:1px solid var(--eka-border);}
h1,h2,h3,h4{color:var(--eka-text)!important;font-weight:600!important;}
p,li,span,label{color:var(--eka-text);}
.eka-card{background:var(--eka-card);border:1px solid var(--eka-border);border-radius:12px;padding:16px 18px;margin-bottom:12px;}
.eka-title{font-size:22px;font-weight:600;color:var(--eka-text);margin-bottom:4px;}
.eka-sub{font-size:13px;color:var(--eka-muted);line-height:1.6;}
.eka-badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;background:var(--eka-primary-soft);color:var(--eka-primary);margin-right:6px;}
.eka-badge-green{background:#E1F5EE;color:var(--eka-success);}
.eka-badge-warn{background:#FFF4E5;color:var(--eka-warn);}
.eka-mock{background:#FFF4E5;color:#854F0B;border:1px solid #F0C987;border-radius:10px;padding:10px 14px;font-size:13px;margin-bottom:14px;line-height:1.6;}
.eka-section{font-size:15px;font-weight:600;color:var(--eka-text);margin:18px 0 8px 0;}
.eka-kv{font-size:13px;color:var(--eka-muted);line-height:1.8;}
.stButton button{border-radius:8px;border:1px solid var(--eka-border);font-size:13px;}
div[data-testid="stMetric"]{background:#FFFFFF;border:1px solid var(--eka-border);border-radius:12px;padding:12px 14px;}
div[data-testid="stExpander"]{background:#FFFFFF;border:1px solid var(--eka-border);border-radius:10px;}
hr{border-color:var(--eka-border);}
</style>
"""


def inject_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str, badge: str | None = None) -> None:
    badge_html = f'<span class="eka-badge">{badge}</span>' if badge else ""
    st.markdown(
        f'<div class="eka-card"><div class="eka-title">{title} {badge_html}</div>'
        f'<div class="eka-sub">{subtitle}</div></div>',
        unsafe_allow_html=True,
    )


def mock_banner(is_mock: bool) -> None:
    if is_mock:
        st.markdown(
            '<div class="eka-mock"><strong>模拟运行提示：</strong>未配置 DeepSeek API Key。'
            '界面、文档解析、向量检索、LangGraph 工作流与工具调用均为真实代码逻辑；'
            '答案由本地抽取式模拟器基于真实检索片段生成，<strong>不是大模型回答</strong>。</div>',
            unsafe_allow_html=True,
        )


def section(title: str) -> None:
    st.markdown(f'<div class="eka-section">{title}</div>', unsafe_allow_html=True)


def show_api_error(exc: Exception) -> None:
    message = getattr(exc, "message", str(exc))
    detail = getattr(exc, "detail", "")
    st.error(f"操作失败：{message}")
    if detail:
        st.caption(f"详细说明：{detail}")
