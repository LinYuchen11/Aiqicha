"""页面五：RAG 评估中心。真实运行实验、计算指标、绘图对比、人工评估录入。"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from frontend import api_client as api
from frontend.components.render import metric_cards
from frontend.components.style import mock_banner, page_header, section, show_api_error

EXPERIMENTS = {
    "chunking": "实验一：文本分块策略",
    "topk": "实验二：Top-K 检索数量",
    "retrieval": "实验三：检索方式对比",
    "rerank": "实验四：重排序优化（原始 / 规则 / CrossEncoder）",
    "embedding": "实验五：Embedding 模型对照（hash vs BGE）",
}


def _bar_chart(rows: list[dict], metric: str) -> go.Figure:
    labels = [row["方案"] for row in rows]
    values = [float(row.get(metric) or 0) for row in rows]
    fig = go.Figure(
        data=[go.Bar(x=labels, y=values, marker_color="#185FA5", text=[f"{v:.4f}" for v in values], textposition="outside")]
    )
    fig.update_layout(
        title=f"不同方案的 {metric} 对比", xaxis_title="实验方案", yaxis_title=metric,
        template="plotly_white", height=380, margin=dict(t=60, b=40),
    )
    return fig


def _conclusion(rows: list[dict], metric: str) -> str:
    valid = [row for row in rows if row.get(metric) is not None]
    if not valid:
        return f"暂无可比较的 {metric} 数据，请先运行实验。"
    best = max(valid, key=lambda row: row[metric])
    worst = min(valid, key=lambda row: row[metric])
    if best[metric] == worst[metric]:
        return f"本次真实运行的 {len(valid)} 个方案 {metric} 相同（{best[metric]}），未观察到差异。"
    return (
        f"本次真实运行的 {len(valid)} 个方案中，「{best['方案']}」的 {metric} 最高（{best[metric]}），"
        f"「{worst['方案']}」最低（{worst[metric]}）。"
        "该结论仅适用于当前模拟文档集合、测试问题集与所用向量档位。"
    )


page_header(
    "RAG 评估中心",
    "全部指标由真实检索运行计算，绝不填充虚构数据。人工评估项需人工录入，默认状态为「待人工评估」。",
    badge="可复现实验",
)
try:
    mock_banner(bool(api.health().get("是否为模拟运行", True)))
except Exception as exc:
    show_api_error(exc)

try:
    overview = api.eval_overview()
except Exception as exc:
    overview = {}
    show_api_error(exc)

questions = overview.get("问题集", [])
question_stats = overview.get("问题集统计", {})
metric_cards({
    "测试问题数": question_stats.get("总题数", 0),
    "已完成实验": overview.get("已完成实验数", 0),
    "人工评估状态": (overview.get("人工评估") or {}).get("状态", "待人工评估"),
    "向量档位": (overview.get("向量档位") or {}).get("实际档位", "-"),
})

tab_questions, tab_experiments, tab_human = st.tabs(["测试问题集", "实验运行与结果", "人工评估"])

with tab_questions:
    section("统一测试问题集")
    st.caption(
        "覆盖简单查询、条件查询、跨文档查询、连续追问、无答案问题与工具调用。"
        "工具调用题由集成测试验证，不参与检索指标；连续追问在自动评估中使用补全后的完整问句。"
    )
    if questions:
        st.dataframe(
            [
                {
                    "题号": item["id"], "类型": item["类型"], "问题": item["问题"],
                    "评估类型": item["评估类型"], "相关文档": "、".join(item.get("相关文档") or []) or "-",
                    "相关章节": "、".join(item.get("相关章节") or []) or "-",
                }
                for item in questions
            ],
            width="stretch", hide_index=True,
        )
        selected = st.selectbox("查看标准答案", [item["id"] for item in questions])
        item = next((q for q in questions if q["id"] == selected), None)
        if item:
            st.markdown(f"**问题**：{item['问题']}")
            st.markdown(f"**检索问题**：{item.get('检索问题', '-')}")
            st.markdown(f"**标准答案**：{item['标准答案']}")
            st.caption(f"相关块标识：{'、'.join(item.get('相关块标识') or []) or '无（无答案题）'}")
    else:
        st.info("测试问题集尚未生成，请检查 data/evaluation/test_questions.json。")
    with st.expander("指标计算方法说明"):
        for key, value in (overview.get("指标说明") or {}).items():
            st.markdown(f"- **{key}**：{value}")

with tab_experiments:
    section("实验参数设置")
    col_a, col_b = st.columns(2)
    with col_a:
        experiment = st.selectbox("选择实验", list(EXPERIMENTS), format_func=lambda x: EXPERIMENTS[x])
    with col_b:
        weight = st.slider("混合检索向量权重", 0.0, 1.0, 0.6, 0.05)
    st.caption(
        "实验一会按不同 Chunk Size / Overlap / 分块策略重建独立向量集合，不会影响在线问答的知识库；"
        "实验二至四直接使用当前生产知识库。"
    )
    if st.button("运行实验（真实执行）", type="primary"):
        with st.spinner("正在逐题检索并计算指标，请稍候…"):
            try:
                result = api.run_evaluation(experiment, {"hybrid_weight": weight})
                st.session_state.eka_last_run = result
                st.success(f"实验已完成：{result.get('id', '')}")
            except Exception as exc:
                show_api_error(exc)

    run = st.session_state.get("eka_last_run")
    if run is None:
        try:
            history = api.eval_runs().get("实验记录", [])
            completed = [item for item in history if item.get("status") == "已完成"]
            if completed:
                run = api.eval_run_detail(completed[0]["id"]).get("实验")
        except Exception:
            run = None

    if run and run.get("metrics", {}).get("方案"):
        rows = run["metrics"]["方案"]
        section(f"{run['metrics'].get('实验名称', '实验结果')}｜运行编号 {run.get('id', '-')}")
        for note in (run["metrics"].get("跳过方案说明") or run["metrics"].get("未运行方案说明") or []):
            st.warning(f"未运行说明：{note}")
        st.caption(
            f"参与检索题数：{run['metrics'].get('参与检索题数', '-')}｜"
            f"跳过工具调用题数：{run['metrics'].get('跳过工具调用题数', '-')}｜"
            f"总耗时：{run['metrics'].get('总耗时秒', '-')} 秒｜"
            f"向量档位：{(run['metrics'].get('运行档位') or {}).get('实际档位', '-')}"
        )
        st.dataframe(
            [
                {
                    "方案": row["方案"], "Recall@K": row.get("Recall@K"), "MRR": row.get("MRR"),
                    "命中率": row.get("命中率"), "平均响应时间ms": row.get("平均响应时间ms"),
                    "无答案正确率": row.get("无答案正确率"),
                    "答案-上下文一致性": row.get("答案-上下文一致性"),
                    "参数": str(row.get("参数", "")),
                }
                for row in rows
            ],
            width="stretch", hide_index=True,
        )
        chart_col_1, chart_col_2 = st.columns(2)
        with chart_col_1:
            st.plotly_chart(_bar_chart(rows, "Recall@K"), width="stretch")
        with chart_col_2:
            st.plotly_chart(_bar_chart(rows, "MRR"), width="stretch")
        section("实验结论")
        st.info(_conclusion(rows, "MRR"))
        st.caption(_conclusion(rows, "Recall@K"))
        with st.expander("逐题明细（真实检索结果）"):
            for row in rows:
                st.markdown(f"**{row['方案']}**")
                st.dataframe(row.get("每题明细", []), width="stretch", hide_index=True)
    else:
        st.info("尚无已完成的实验。点击上方按钮真实运行一组实验后，这里会显示指标与图表。")

    section("历史实验记录")
    try:
        runs = api.eval_runs().get("实验记录", [])
        if runs:
            st.dataframe(
                [
                    {"运行编号": item["id"], "实验": EXPERIMENTS.get(item["experiment"], item["experiment"]),
                     "状态": item["status"], "开始时间": item["started_at"], "备注": item.get("notes") or "-"}
                    for item in runs
                ],
                width="stretch", hide_index=True,
            )
        else:
            st.caption("暂无实验记录。")
    except Exception as exc:
        show_api_error(exc)

with tab_human:
    section("答案正确性与来源引用准确性（人工录入）")
    st.warning(
        "人工评估必须由人判读，系统不会自动生成分数。未录入前，报告中的人工评估项保持「待人工评估」状态。"
    )
    if questions:
        col_a, col_b = st.columns(2)
        with col_a:
            qid = st.selectbox("题号", [item["id"] for item in questions])
        with col_b:
            evaluator = st.text_input("评估人", "面试官")
        correct = st.selectbox("答案正确性（0/0.5/1，留空表示未评分）", ["未评分", "0", "0.5", "1"], index=0)
        citation = st.selectbox("来源引用准确性（0/0.5/1，留空表示未评分）", ["未评分", "0", "0.5", "1"], index=0)
        note = st.text_area("评估备注", "")
        if st.button("保存人工评估记录"):
            try:
                api.save_human_eval({
                    "question_id": qid,
                    "answer_correctness": None if correct == "未评分" else float(correct),
                    "citation_accuracy": None if citation == "未评分" else float(citation),
                    "note": note, "evaluator": evaluator,
                })
                st.success("已保存。该记录与自动指标分开统计。")
                st.rerun()
            except Exception as exc:
                show_api_error(exc)
    try:
        human = api.human_evals()
        summary = human.get("汇总", {})
        metric_cards({
            "已录入条数": summary.get("已录入条数", 0),
            "答案正确性已评分": summary.get("答案正确性已评分数", 0),
            "来源引用已评分": summary.get("来源引用已评分数", 0),
            "状态": summary.get("状态", "待人工评估"),
        })
        records = human.get("记录", [])
        if records:
            st.dataframe(records, width="stretch", hide_index=True)
    except Exception as exc:
        show_api_error(exc)
