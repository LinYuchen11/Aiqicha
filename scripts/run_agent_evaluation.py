"""真实运行 Agent 专项评估，并把结果写成中文 Markdown 到 docs/agent_evaluation_report.md。

用法：python scripts/run_agent_evaluation.py

- 真实逐题调用 chat_service.chat()，不编造任何通过记录或数值；
- 全部指标由 run_agent_evaluation() 聚合后原样写入报告；
- 评估对象为 Mock 规则决策器，报告明确标注「真实 DeepSeek 模式下未验证」；
- 评估在函数内部重定向到临时目录，不读写真实运行库。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.agent_evaluation_service import run_agent_evaluation  # noqa: E402

OUTPUT = ROOT / "docs" / "agent_evaluation_report.md"


def _fmt_rate(metric: dict) -> str:
    """把指标字典格式化为「百分比（分子/分母）」，无样本如实写「无样本」。"""
    value = metric.get("值")
    if value is None or metric.get("无样本"):
        return "无样本"
    if "总调用" in metric:
        den = metric["总调用"]
        num = metric["成功"]
    elif "有期望工具题数" in metric:
        den = metric["有期望工具题数"]
        num = metric["命中"]
    else:
        den = metric.get("总题数", 0)
        num = metric.get("命中", metric.get("完成", 0))
    return f"{value * 100:.2f}%（{num}/{den}）"


def _tools(value: list[str]) -> str:
    return "、".join(value) if value else "（无）"


def _cell(text: str) -> str:
    """表格单元格：去掉换行、转义竖线，避免破坏 Markdown 表格。"""
    return str(text).replace("\n", " ").replace("|", "\\|").strip()


def build_markdown(data: dict) -> str:
    metrics = data["指标"]
    env = data["运行环境"]
    lines: list[str] = [
        "# Agent 专项评估报告",
        "",
        "> 本报告由 `scripts/run_agent_evaluation.py` 真实运行 `run_agent_evaluation()` 后生成，"
        "逐题真实调用 `chat_service.chat()`，四项指标与逐题明细均为真实计算结果，不含任何人工编造的数值。",
        "",
        f"> **评估结论适用于「Mock 规则决策器」**：当前无 `.env`、无 DeepSeek Key，"
        f"LLM 运行模式为 `{env['LLM 运行模式']}`，意图/规划/答案分别由规则决策器、规则规划器、"
        "本地抽取式模拟器产生，并非真实大模型推理结果。",
        "",
        "> ⚠️ **真实 DeepSeek 模式下未验证**：本报告全部结论仅在 Mock 规则决策器下成立，"
        "未接入 DeepSeek API Key、未调用真实模型，不能代表真实模型下的意图识别、工具选择与任务完成能力。",
        "",
        "## 一、运行环境",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 评估对象 | {_cell(data['评估对象'])} |",
        f"| LLM 运行模式 | {_cell(env['LLM 运行模式'])}（is_mock={env['是否 Mock']}） |",
        f"| 决策器 | {_cell(env['决策器'])} |",
        f"| 意图决策来源（样例） | {_cell(env['意图决策来源（样例）'])} |",
        f"| 规划来源（样例） | {_cell(env['规划来源（样例）'])} |",
        f"| Embedding 档位 | {_cell(env['Embedding 档位'])} |",
        f"| DeepSeek Key 已配置 | {env['DeepSeek Key 已配置']} |",
        f"| 题数 | {data['题数']} |",
        f"| 数据集 | `{_cell(data['数据集路径'])}` |",
        f"| 隔离方式 | {_cell(env['隔离方式'])} |",
        f"| 样例文档导入 | 已导入 {env['样例文档导入'].get('已导入', 0)} 篇，"
        f"文档总数 {env['样例文档导入'].get('文档总数', 0)} 篇 |",
        "",
        "## 二、四项指标（真实数值）",
        "",
        "| 指标 | 数值 | 说明 |",
        "| --- | --- | --- |",
        f"| 意图识别准确率 | {_fmt_rate(metrics['意图识别准确率'])} | "
        f"命中 {metrics['意图识别准确率']['命中']}/{metrics['意图识别准确率']['总题数']} 题 |",
        f"| 工具选择准确率 | {_fmt_rate(metrics['工具选择准确率'])} | "
        f"分母为有期望工具的 {metrics['工具选择准确率']['有期望工具题数']} 题 |",
        f"| 工具执行成功率 | {_fmt_rate(metrics['工具执行成功率'])} | "
        f"成功 {metrics['工具执行成功率']['成功']}/{metrics['工具执行成功率']['总调用']} 次工具调用"
        + ("（本次无任何工具调用，如实记为无样本，未填 1.0）" if metrics['工具执行成功率']['无样本'] else "")
        + " |",
        f"| 任务完成率 | {_fmt_rate(metrics['任务完成率'])} | "
        f"完成 {metrics['任务完成率']['完成']}/{metrics['任务完成率']['总题数']} 题 |",
        "",
        "> 说明：标注题均以 Mock 规则决策器下系统真实、可复现的行为为准人工编写，"
        "因此在该确定性环境下各项指标可能均为 100%；这反映「规则决策器在其规则覆盖范围内行为一致」，"
        "**不等于真实模型具备同等能力，也不作任何美化**。",
        "",
        "## 三、逐题明细（真实运行结果）",
        "",
        "| 题号 | 类别 | 期望意图 | 实际意图 | 意图 | 期望工具 | 实际工具 | 工具一致 | 待确认 | 耗时(ms) | 完成 | 回答摘要 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in data["逐题明细"]:
        lines.append(
            f"| {_cell(d['题号'])} | {_cell(d['类别'])} | {_cell(d['期望意图'])} | "
            f"{_cell(d['实际意图'])} | {'✓' if d['意图命中'] else '✗'} | "
            f"{_cell(_tools(d['期望工具']))} | {_cell(_tools(d['实际工具']))} | "
            f"{'✓' if d['工具集合一致'] else '✗'} | "
            f"{'有' if d['实际待确认'] else '无'} | {d['耗时毫秒']} | "
            f"{'✓' if d['是否完成'] else '✗'} | {_cell(d['回答摘要'])} |"
        )
    lines += [
        "",
        "「工具一致」列对所有题（含空期望工具题）均按集合比较给出；空期望工具的题在「工具选择准确率」"
        "分母中记为不适用，不计入该指标（详见第四节口径）。",
        "",
        "### 完成判定明细",
        "",
        "| 题号 | 完成规则 | 是否完成 | 判定说明 | 异常 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in data["逐题明细"]:
        lines.append(
            f"| {_cell(d['题号'])} | `{_cell(d['完成规则'])}` | {'✓' if d['是否完成'] else '✗'} | "
            f"{_cell(d['完成判定说明'])} | {_cell(d['异常'] or '无')} |"
        )
    lines += [
        "",
        "## 四、指标计算方法与完成判定规则",
        "",
        "### 4.1 四项指标口径",
        "",
        "| 指标 | 计算方法 |",
        "| --- | --- |",
    ]
    for key, desc in data["指标说明"].items():
        lines.append(f"| {key} | {_cell(desc)} |")
    lines += [
        "",
        "### 4.2 任务完成判定规则表（由代码确定性执行，不接受主观填写）",
        "",
        "所有规则隐含基础条件：无异常 + answer 非空 + 不含失败标志 + "
        "pending_confirmation 有无与 needs_confirmation 一致。",
        "",
        "| 规则标识 | 附加判定条件 |",
        "| --- | --- |",
    ]
    for rule, desc in data["完成判定规则"].items():
        lines.append(f"| `{rule}` | {_cell(desc)} |")
    lines += [
        "",
        "## 五、局限说明",
        "",
        "1. **Mock 规则决策器**：意图与规划均由关键词规则产生，答案为本地抽取式模拟器对检索片段的原文摘录，"
        "不是大模型生成；本评估衡量的是规则决策器在其规则范围内的行为一致性，不代表语义理解或推理能力。",
        "2. **真实 DeepSeek 模式下未验证**：未配置 API Key、未产生任何真实模型调用，"
        "报告中的四项指标不能外推到真实模型。",
        "3. **标注集规模有限**：共 " + str(data["题数"]) + " 题，基于 6 份模拟企业制度文档人工编写，"
        "覆盖知识查询、IT 咨询、工单查询、工单创建（待确认）、闲聊、无答案、多轮补答等场景，"
        "结论不能外推到真实企业知识库或更广泛的问法。",
        "4. **工单创建不落库**：所有工单创建类题目只到「待确认」状态，评估全程不调用 "
        "`chat_service.confirm()`，未向工单表写入任何数据；且整体运行在临时目录，不污染真实运行库。",
        "5. **hash 向量**：默认 Embedding 档位为词面哈希向量（非语义 Embedding），"
        "「无答案」题依赖检索是否命中；换用语义 Embedding 后相关题的命中情况可能变化。",
        "6. **工具选择准确率分母**：严格按「有期望工具的题数」计算；空期望工具题不计入该指标分母，"
        "但其集合比较结果仍如实写入逐题明细，避免空集合被误判。",
        "7. 若某项指标因环境原因无样本（如整次运行无任何工具调用），报告如实记为「无样本」，"
        "不填 1.0、不做美化。",
        "",
        "## 六、结论",
        "",
        f"- 运行模式：{_cell(env['决策器'])}；**真实 DeepSeek 模式下未验证**。",
        f"- 意图识别准确率：{_fmt_rate(metrics['意图识别准确率'])}；"
        f"工具选择准确率：{_fmt_rate(metrics['工具选择准确率'])}；"
        f"工具执行成功率：{_fmt_rate(metrics['工具执行成功率'])}；"
        f"任务完成率：{_fmt_rate(metrics['任务完成率'])}。",
        f"- {_cell(data['结论标注'])}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    data = run_agent_evaluation()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_markdown(data), encoding="utf-8")

    metrics = data["指标"]
    print("=" * 60)
    print("Agent 专项评估已完成（Mock 规则决策器；真实 DeepSeek 模式下未验证）")
    print(f"题数：{data['题数']}")
    print(f"意图识别准确率：{_fmt_rate(metrics['意图识别准确率'])}")
    print(f"工具选择准确率：{_fmt_rate(metrics['工具选择准确率'])}")
    print(f"工具执行成功率：{_fmt_rate(metrics['工具执行成功率'])}")
    print(f"任务完成率：{_fmt_rate(metrics['任务完成率'])}")
    print(f"报告已生成：{OUTPUT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
