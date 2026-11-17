"""单元测试：文本分块参数、策略与来源信息保留。"""
from __future__ import annotations

import pytest

from backend.core.errors import ParamError
from backend.rag.chunker import split_into_chunks
from backend.rag.parsers import ParsedBlock


def _blocks() -> list[ParsedBlock]:
    return [ParsedBlock(text=("员工申请年假需提前三个工作日提交申请，由部门负责人审批。" * 20),
                        section="一、年假申请规定", page=2)]


def test_chunk_size_and_overlap():
    chunks = split_into_chunks(_blocks(), "doc1", chunk_size=100, overlap=20)
    assert len(chunks) > 3
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_section_and_page_preserved():
    chunks = split_into_chunks(_blocks(), "doc1", chunk_size=120, overlap=30)
    assert all(chunk.section == "一、年假申请规定" for chunk in chunks)
    assert all(chunk.page == 2 for chunk in chunks)
    assert all(chunk.doc_id == "doc1" for chunk in chunks)


def test_invalid_overlap():
    with pytest.raises(ParamError):
        split_into_chunks(_blocks(), "doc1", chunk_size=100, overlap=100)
    with pytest.raises(ParamError):
        split_into_chunks(_blocks(), "doc1", chunk_size=20, overlap=0)


def test_fixed_vs_semantic_strategy():
    fixed = split_into_chunks(_blocks(), "doc1", 100, 20, strategy="fixed")
    semantic = split_into_chunks(_blocks(), "doc1", 100, 20, strategy="semantic")
    assert fixed and semantic
    assert fixed[0].text.endswith("。") or len(fixed[0].text) == 100
    assert all(len(chunk.text) == 100 for chunk in fixed[:-1])


def test_empty_blocks():
    assert split_into_chunks([ParsedBlock(text="   ", section=None)], "doc1") == []
