"""真实运行 5 组 RAG 实验，并依据真实结果生成 docs/evaluation_report.md。

用法：python scripts/run_evaluation.py
不会填充任何虚构数据；模型不可用、人工评估项一律如实标注，不代填分数。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.db import init_database  # noqa: E402
from backend.services.document_service import ensure_sample_documents  # noqa: E402
from backend.services.evaluation_service import report_data, run_experiment  # noqa: E402

LABELS = {
    "chunking": "实验一：文本分块策略",
    "topk": "实验二：Top-K 检索数量",
    "retrieval": "实验三：检索方式对比",
    "rerank": "实验四：重排序优化（原始 / 规则 / CrossEncoder）",
    "embedding": "实验五：Embedding 模型对照（hash vs BGE）",
}


def _fmt(value) -> str:
    return "—" if value is None else str(value)


def _conclusion(rows: list[dict], metric: str) -> str:
    valid = [row for row in rows if row.get(metric) is not None]
    if not valid:
        return f"暂无可比较的 {metric} 数据。"
    best = max(valid, key=lambda row: row[metric])
    worst = min(valid, key=lambda row: row[metric])
    if best[metric] == worst[metric]:
        return f"各方案 {metric} 相同（{best[metric]}），本次实验未观察到差异。"
    return (
        f"「{best['方案']}」的 {metric} 最高（{best[metric]}），"
        f"「{worst['方案']}」最低（{worst[metric]}）。"
    )


def build_markdown(data: dict) -> str:
    vector = data["向量档位"]
    lines = [
        "# RAG 优化实验报告",
        "",
        "> 本报告中的全部指标均由 `scripts/run_evaluation.py` 真实运行检索实验后计算，"
        "不含任何人工编造的实验数据。人工评估项需人工录入，报告不代填分数。",
        "",
        "## 一、实验环境",
        "",
        f"- 向量方案：{vector.get('模型名称', '-')}",
        f"- 配置档位：{vector.get('配置档位', '-')}｜实际档位：{vector.get('实际档位', '-')}",
        f"- 向量维度：{vector.get('向量维度', '-')}｜是否语义向量：{_fmt(vector.get('是否语义向量'))}",
        f"- 正式演示推荐档位：{vector.get('正式演示推荐档位', '-')}（{vector.get('推荐模型', '-')}）",
        f"- 模型降级原因：{vector.get('降级原因', '无')}",
        f"- 测试问题集：{data['问题集统计'].get('总题数', 0)} 题，按类型分布：{data['问题集统计'].get('按类型', {})}",
        "",
        "> 默认档位 hash 是词面哈希向量（字符 n-gram 哈希），**不是语义 Embedding**；"
        "其语义区分度弱于本地 BGE。实验五用同一测试集对照两档，"
        "BGE 不可用时只记录未运行说明，不生成任何模型指标。",
        "",
        "## 二、实验结果",
        "",
    ]
    for run in data["实验记录"]:
        metrics = run.get("metrics") or {}
        rows = metrics.get("方案") or []
        lines += [
            f"### {metrics.get('实验名称', LABELS.get(run['experiment'], run['experiment']))}",
            "",
            f"- 运行编号：`{run['id']}`",
            f"- 开始时间：{run['started_at']}｜完成时间：{run['finished_at']}",
            f"- 参与检索题数：{metrics.get('参与检索题数', '-')}｜跳过工具调用题数：{metrics.get('跳过工具调用题数', '-')}",
            f"- 本次运行总耗时：{metrics.get('总耗时秒', '-')} 秒",
            "",
            "| 方案 | Recall@K | MRR | 命中率 | 平均响应时间(ms) | 无答案正确率 | 答案-上下文一致性 | 关键参数 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            lines.append(
                f"| {row['方案']} | {_fmt(row.get('Recall@K'))} | {_fmt(row.get('MRR'))} | "
                f"{_fmt(row.get('命中率'))} | {_fmt(row.get('平均响应时间ms'))} | "
                f"{_fmt(row.get('无答案正确率'))} | {_fmt(row.get('答案-上下文一致性'))} | "
                f"{str(row.get('参数', ''))} |"
            )
        lines += [
            "",
            f"**结论（MRR）**：{_conclusion(rows, 'MRR')}",
            "",
            f"**结论（Recall@K）**：{_conclusion(rows, 'Recall@K')}",
            "",
            f"**结论（答案-上下文一致性）**：{_conclusion(rows, '答案-上下文一致性')}",
            "",
        ]
        skipped = metrics.get("跳过方案说明") or metrics.get("未运行方案说明") or []
        for note in skipped:
            lines += [f"> ⚠️ 未运行说明：{note}", ""]
        if rows and run["experiment"] == "rerank":
            changed = sum(
                1 for item in (rows[-1].get("每题明细") or [])
                if any(
                    (hit.get("original_rank") or hit.get("rank")) != hit.get("rank")
                    for hit in item.get("召回块") or []
                )
            )
            lines += [
                f"重排序后逐题明细中发生排名变化的召回块数量：{changed} 个"
                "（按 original_rank 与 rank 比较统计）。"
                "排序是否带来检索效果提升，以本节 MRR / Recall@K 是否变化为准。",
                "",
            ]
    lines += [
        "## 三、指标计算方法",
        "",
        "| 指标 | 计算方法 |",
        "| --- | --- |",
    ]
    for key, value in data["指标说明"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## 四、人工评估状态",
        "",
        f"- 状态：{data['人工评估'].get('状态', '待人工评估')}",
        f"- 已录入条数：{data['人工评估'].get('已录入条数', 0)}",
        f"- 答案正确性均值：{_fmt(data['人工评估'].get('答案正确性均值'))}",
        f"- 来源引用准确性均值：{_fmt(data['人工评估'].get('来源引用均值'))}",
        "",
        "答案正确性与来源引用准确性属于人工判读任务，系统不自动生成分数。"
        "可在「RAG 评估中心 → 人工评估」页面录入后再重新生成本报告。",
        "",
        "## 五、局限与后续优化",
        "",
        "1. `hash` 档是词面哈希向量，不是语义 Embedding；实验五在同一测试集上与 BGE 对照。",
        "2. 规则式重排序是确定性打分，不是模型；CrossEncoder 方案只有在模型真实加载成功时才运行，"
        "否则报告明确标注未运行，不把降级结果写成模型结果。",
        "3. 标准答案采用人工审核的「文档::章节」相关文本范围，按文档配对、分母固定；"
        "章节级粒度仍可能包含少量无关句子，不等同于逐块人工标注。",
        "4. 「答案-上下文一致性」是词面支撑率代理指标，不调用大模型，不能替代语义忠实度评估与人工判读。",
        "5. 测试问题集基于 6 份模拟企业制度文档人工编写，规模有限，结论不能外推到真实企业知识库。",
        "6. 工具调用类问题不参与检索指标，由集成测试场景 D、G 验证真实执行。",
        "7. 若某项优化未带来提升，报告如实保留原始数值，不做美化。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    init_database()
    imported = ensure_sample_documents()
    print(f"模拟文档同步：{imported}")
    run_ids = []
    for experiment in LABELS:
        print(f"正在运行 {LABELS[experiment]} …")
        result = run_experiment(experiment, {})
        run_ids.append(result["id"])
        print(f"  完成：{result['id']}，耗时 {result['metrics']['总耗时秒']} 秒")
    data = report_data()
    data["实验记录"] = [run for run in data["实验记录"] if run["id"] in run_ids]
    data["实验记录"].reverse()
    output = ROOT / "docs" / "evaluation_report.md"
    output.write_text(build_markdown(data), encoding="utf-8")
    print(f"实验报告已生成：{output}")


if __name__ == "__main__":
    main()
