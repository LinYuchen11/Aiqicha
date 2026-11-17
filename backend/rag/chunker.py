"""文本分块：按 Chunk Size / Overlap 切分，尽量在句末断开，并保留章节与页码。"""
from __future__ import annotations

from dataclasses import dataclass

from backend.core.errors import ParamError
from backend.rag.parsers import ParsedBlock

_SENTENCE_END = set("。！？；!?;\n")


@dataclass
class Chunk:
    id: str
    doc_id: str
    chunk_index: int
    text: str
    section: str | None
    page: int | None
    char_start: int
    char_end: int


def split_into_chunks(
    blocks: list[ParsedBlock],
    doc_id: str,
    chunk_size: int = 400,
    overlap: int = 80,
    strategy: str = "semantic",
) -> list[Chunk]:
    """生成带来源信息的文本块。chunk_size 按字符计（中文场景更稳定）。

    strategy=semantic 时优先在句末断开以保留语义完整；
    strategy=fixed 时为纯固定长度分块，用于评估实验中的策略对比。
    """
    if chunk_size < 50:
        raise ParamError("分块大小过小", "Chunk Size 不得小于 50 个字符")
    if overlap < 0 or overlap >= chunk_size:
        raise ParamError("分块重叠参数不合法", "Chunk Overlap 必须大于等于 0 且小于 Chunk Size")

    chunks: list[Chunk] = []
    global_offset = 0
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        start = 0
        length = len(text)
        while start < length:
            end = min(start + chunk_size, length)
            if end < length and strategy != "fixed":
                cut = -1
                lower = max(start + chunk_size // 2, start + 1)
                for i in range(end, lower, -1):
                    if text[i - 1] in _SENTENCE_END:
                        cut = i
                        break
                if cut > start:
                    end = cut
            piece = text[start:end].strip()
            if len(piece) >= 5:
                index = len(chunks)
                chunks.append(
                    Chunk(
                        id=f"{doc_id}-c{index:04d}",
                        doc_id=doc_id,
                        chunk_index=index,
                        text=piece,
                        section=block.section,
                        page=block.page,
                        char_start=global_offset + start,
                        char_end=global_offset + end,
                    )
                )
            if end >= length:
                break
            start = max(start + 1, end - overlap)
        global_offset += length + 1
    return chunks
