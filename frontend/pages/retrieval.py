"""页面三：检索调试。展示分数、来源、原始片段与重排序前后对比。"""
from __future__ import annotations

import streamlit as st

from frontend import api_client as api
from frontend.components.render import metric_cards
from frontend.components.style import mock_banner, page_header, section, show_api_error

page_header(
    "检索调试",
    "直接调用后端检索器，查看向量分、关键词分、混合得分、文本块来源，并对比重排序前后的结果顺序。",
    badge="混合检索",
)
try:
    mock_banner(bool(api.health().get("是否为模拟运行", True)))
except Exception as exc:
    show_api_error(exc)

query = st.text_input("测试问题", placeholder="例如：设计类软件安装需要谁审批？")
col_a, col_b, col_c = st.columns(3)
with col_a:
    top_k = st.slider("Top-K", 1, 15, 5)
with col_b:
    mode = st.selectbox("检索方式", ["hybrid", "vector", "keyword"],
                        format_func=lambda x: {"hybrid": "混合检索", "vector": "纯向量检索", "keyword": "关键词检索"}[x])
with col_c:
    weight = st.slider("向量权重", 0.0, 1.0, 0.6, 0.05)
compare = st.checkbox("同时对比重排序前后结果", value=True)

if query and st.button("执行检索", type="primary"):
    try:
        payload = {"query": query, "top_k": top_k, "mode": mode, "hybrid_weight": weight, "rerank": False}
        base = api.retrieval_search(payload)
        results = base.get("results", [])

        section("检索概况")
        metric_cards({
            "召回文本块": len(results),
            "总向量数": base.get("total_vectors", 0),
            "耗时ms": base.get("elapsed_ms", 0),
            "最高分": round(results[0]["score"], 4) if results else None,
        })
        st.caption(base.get("message", ""))

        section("检索结果")
        if not results:
            st.warning("未召回任何文本块。请检查知识库是否已导入文档，或更换关键词。")
        else:
            rows = [
                {
                    "排名": item["rank"], "文件名称": item["doc_name"],
                    "章节": item.get("section") or "-", "页码": item.get("page") or "-",
                    "综合分": item["score"], "向量分": item["vector_score"],
                    "关键词分": item["keyword_score"],
                    "文本片段": item["snippet"][:90],
                }
                for item in results
            ]
            st.dataframe(rows, width="stretch", hide_index=True)
            for item in results:
                with st.expander(f"原始片段｜第 {item['rank']} 名｜《{item['doc_name']}》"):
                    st.caption(f"文本块标识：{item['chunk_id']}｜文档编号：{item['doc_id']}")
                    st.text(item["text"])

        if compare:
            section("重排序前后对比")
            reranked = api.retrieval_search({**payload, "rerank": True})
            left, right = st.columns(2)
            with left:
                st.markdown("**原始检索排序**")
                st.dataframe(
                    [{"排名": item["rank"], "文件": item["doc_name"], "综合分": item["score"]} for item in results],
                    width="stretch", hide_index=True,
                )
            with right:
                st.markdown(f"**重排序后**（{reranked.get('rerank_method', '规则式')}）")
                st.dataframe(
                    [
                        {"排名": item["rank"], "原排名": item.get("original_rank") or "-",
                         "文件": item["doc_name"], "重排分": item.get("rerank_score")}
                        for item in reranked.get("results", [])
                    ],
                    width="stretch", hide_index=True,
                )
            st.caption("规则式重排序为确定性打分（非模型），综合原始得分、查询词覆盖率与章节标题匹配度。")
    except Exception as exc:
        show_api_error(exc)
