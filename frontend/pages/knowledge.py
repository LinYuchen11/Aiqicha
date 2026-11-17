"""页面二：知识库管理。上传、列表、状态、详情、删除、重处理、检索测试。"""
from __future__ import annotations

import streamlit as st

from frontend import api_client as api
from frontend.components.style import mock_banner, page_header, section, show_api_error
from frontend.components.render import metric_cards

page_header(
    "知识库管理",
    "上传企业文档后自动完成解析、清洗、分块、Embedding 与持久化向量存储；所有数据保存在本地 SQLite。",
    badge="RAG 知识库",
)
try:
    mock_banner(bool(api.health().get("是否为模拟运行", True)))
except Exception as exc:
    show_api_error(exc)

section("文档上传")
uploaded = st.file_uploader(
    "选择文件（支持 PDF / DOCX / TXT / MD，可多选）",
    type=["pdf", "docx", "txt", "md"],
    accept_multiple_files=True,
)
if uploaded and st.button("上传并处理", type="primary"):
    with st.spinner("正在解析与向量化…"):
        try:
            result = api.upload_files([(item.name, item.getvalue()) for item in uploaded])
            st.success(f"处理完成：成功 {result.get('成功数', 0)} 个，失败 {result.get('失败数', 0)} 个。")
            for item in result.get("结果", []):
                if item.get("成功"):
                    st.caption(f"✔ {item['文件名称']}｜文本块 {item['文本块数']} 个｜{item['解析方式']}")
                else:
                    st.error(f"✘ {item['文件名称']}｜{item.get('错误说明', '')}｜{item.get('详细说明', '')}")
            st.rerun()
        except Exception as exc:
            show_api_error(exc)

try:
    data = api.list_documents()
except Exception as exc:
    data = {}
    show_api_error(exc)

section("知识库统计")
stats = data.get("统计", {})
metric_cards({
    "文档总数": stats.get("文档总数", 0),
    "处理成功": stats.get("处理成功", 0),
    "处理失败": stats.get("处理失败", 0),
    "文本块总数": stats.get("文本块总数", 0),
    "向量数量": data.get("向量数量", 0),
})
embedding = data.get("向量模型", {})
st.caption(
    f"当前向量方案：{embedding.get('模型名称', '-')}｜维度 {embedding.get('向量维度', '-')}｜"
    f"配置档位 {embedding.get('配置档位', '-')}｜实际档位 {embedding.get('实际档位', '-')}｜"
    f"向量库 {data.get('向量库', '-')}"
)

section("已上传文档")
docs = data.get("文档", [])
if docs:
    rows = [
        {
            "文件名称": item["filename"], "类型": item["file_type"],
            "大小KB": round(item["size_bytes"] / 1024, 1),
            "状态": item["status"], "文本块": item["chunk_count"],
            "上传时间": item["created_at"], "文档编号": item["id"],
        }
        for item in docs
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    if any(item["error_msg"] for item in docs):
        for item in docs:
            if item["error_msg"]:
                st.error(f"{item['filename']}：{item['error_msg']}")
    selected = st.selectbox("选择文档查看详情", [item["id"] for item in docs],
                            format_func=lambda x: next((d["filename"] for d in docs if d["id"] == x), x))
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("重新处理该文档", width="stretch"):
            try:
                result = api.reprocess_document(selected)
                st.success(result.get("提示", "已重新处理"))
                st.rerun()
            except Exception as exc:
                show_api_error(exc)
    with col_b:
        if st.button("删除该文档", width="stretch"):
            try:
                result = api.delete_document(selected)
                st.success(result.get("提示", "已删除"))
                st.rerun()
            except Exception as exc:
                show_api_error(exc)
    with st.expander("文档详情与文本块"):
        try:
            detail = api.document_detail(selected)
            st.json(detail["文档"])
            chunks = detail["文本块"]
            st.caption(f"共 {len(chunks)} 个文本块，展示前 20 个：")
            st.dataframe(
                [
                    {"序号": c["chunk_index"], "章节": c["section"], "页码": c["page"],
                     "字符范围": f"{c['char_start']}-{c['char_end']}", "内容": c["text"][:160]}
                    for c in chunks[:20]
                ],
                width="stretch", hide_index=True,
            )
        except Exception as exc:
            show_api_error(exc)
else:
    st.info("知识库为空。请上传文档，或重启后端以自动导入预置的模拟企业制度文档。")

section("知识库检索测试")
test_query = st.text_input("输入测试问题", placeholder="例如：年假需要提前几天申请？")
if test_query and st.button("执行检索测试"):
    try:
        outcome = api.retrieval_search({"query": test_query, "top_k": 5, "mode": "hybrid", "hybrid_weight": 0.6, "rerank": False})
        st.caption(f"{outcome.get('message','')}｜耗时 {outcome.get('elapsed_ms',0)} ms｜总向量 {outcome.get('total_vectors',0)}")
        for item in outcome.get("results", []):
            with st.expander(f"第 {item['rank']} 名｜《{item['doc_name']}》｜分数 {item['score']:.4f}"):
                st.caption(f"章节：{item.get('section') or '-'}｜页码：{item.get('page') or '-'}"
                           f"｜向量分 {item['vector_score']:.4f}｜关键词分 {item['keyword_score']:.4f}")
                st.text(item["snippet"])
    except Exception as exc:
        show_api_error(exc)
