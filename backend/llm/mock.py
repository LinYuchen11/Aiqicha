"""Mock 模式：本地抽取式模拟器。

明确声明「模拟运行」，只从真实检索片段中抽取原文，不编造企业制度、不伪装成模型生成。
"""
from __future__ import annotations

import re

from backend.models.schemas import RetrievedChunk
from backend.rag.cleaner import keyword_overlap

MOCK_BANNER = (
    "【模拟运行】当前未配置 DeepSeek API Key，以下内容由本地抽取式模拟器"
    "基于真实检索片段生成，不是大模型回答。"
)


def no_answer(query: str) -> str:
    return (
        f"{MOCK_BANNER}\n\n"
        f"知识库中没有检索到与「{query}」相关的资料，无法据此给出企业制度结论。\n\n"
        "建议：\n"
        "1. 换用更具体的关键词重新提问；\n"
        "2. 在「知识库管理」页面上传相关制度文档后重新检索；\n"
        "3. 若确属制度空白，请咨询对应职能部门，不要依据未经确认的信息办理业务。"
    )


def _location(hit: RetrievedChunk) -> str:
    parts = []
    if hit.section:
        parts.append(f"章节「{hit.section}」")
    if hit.page:
        parts.append(f"第 {hit.page} 页")
    return "（" + "，".join(parts) + "）" if parts else ""


def extractive_answer(query: str, hits: list[RetrievedChunk], max_sources: int = 3) -> str:
    lines = [
        MOCK_BANNER,
        "",
        f"问题：{query}",
        "",
        "依据检索到的企业模拟制度文档，原文摘录如下（仅抽取，不含任何推断）：",
    ]
    for index, hit in enumerate(hits[:max_sources], start=1):
        sentences = [s.strip() for s in re.split(r"(?<=[。！？；\n])", hit.text) if s.strip()]
        if not sentences:
            continue
        ranked = sorted(
            enumerate(sentences), key=lambda pair: -keyword_overlap(query, pair[1])
        )[:2]
        picked = [text for _, text in sorted(ranked, key=lambda pair: pair[0])]
        lines.append(
            f"{index}. 《{hit.doc_name}》{_location(hit)}：{' '.join(picked)}　【来源 {index}】"
        )
    lines += [
        "",
        "说明：以上均为文档原文摘录，未做任何推理或补全；如需完整条款，请展开下方「知识来源」查看原始文本。",
        "若摘录不足以覆盖你的问题，说明当前知识库资料不足，请联系对应部门确认。",
    ]
    return "\n".join(lines)


def chitchat_answer(query: str, intent_label: str) -> str:
    return (
        f"{MOCK_BANNER}\n\n"
        f"已识别为「{intent_label}」。我是企业智能知识助手，可以帮你：\n"
        "1. 查询企业制度、行政流程、IT 服务规范；\n"
        "2. 检索知识库并给出带来源的答案；\n"
        "3. 创建或查询 IT 服务工单。\n\n"
        "请直接描述你的业务问题。"
    )


def unknown_answer() -> str:
    return (
        f"{MOCK_BANNER}\n\n"
        "暂时无法识别这个请求，或该请求超出本系统能力范围。\n"
        "本系统仅支持企业知识查询、IT 服务咨询、工单创建与工单状态查询。"
    )
