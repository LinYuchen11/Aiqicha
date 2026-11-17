"""单元测试：文档解析与文本清洗。"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.errors import FileError, ParseError
from backend.rag.cleaner import clean_text, tokenize_for_search
from backend.rag.parsers import parse_file


def test_clean_text_removes_noise():
    raw = "第一条  内容\x00文字\n第 3 页\n----------------\n第二条  内容"
    cleaned = clean_text(raw)
    assert "\x00" not in cleaned
    assert "第 3 页" not in cleaned
    assert "----------------" not in cleaned
    assert "第一条 内容" in cleaned


def test_tokenize_has_chinese_bigram():
    tokens = tokenize_for_search("年假申请")
    assert "年" in tokens and "年假" in tokens and "假申" in tokens


def test_parse_markdown_preserves_sections(sample_markdown):
    parsed = parse_file(sample_markdown, sample_markdown.name)
    assert parsed.blocks
    assert any("年假" in (block.section or "") for block in parsed.blocks)
    assert "3 个工作日" in parsed.full_text


def test_parse_txt_with_gbk(tmp_path):
    path = tmp_path / "gbk.txt"
    path.write_bytes("## 一、报销规定\n差旅报销需在 5 个工作日内提交。".encode("gbk"))
    parsed = parse_file(path)
    assert "报销规定" in parsed.full_text


def test_parse_docx(tmp_path):
    from docx import Document

    path = tmp_path / "规范.docx"
    doc = Document()
    doc.add_heading("一、软件安装规定", level=1)
    doc.add_paragraph("设计类软件需部门负责人审批后由 IT 服务台安装。")
    doc.save(str(path))
    parsed = parse_file(path)
    assert any("软件安装" in (block.section or "") for block in parsed.blocks)
    assert "IT 服务台" in parsed.full_text


def test_blank_pdf_is_rejected(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ParseError):
        parse_file(path)


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.md"
    path.write_bytes(b"")
    with pytest.raises(FileError) as exc:
        parse_file(path)
    assert "空" in exc.value.message


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "bad.exe"
    path.write_text("内容", encoding="utf-8")
    with pytest.raises(FileError) as exc:
        parse_file(path)
    assert "不支持" in exc.value.message
