"""文档解析：PDF / DOCX / TXT / MD → 带章节与页码信息的文本块。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.core.config import SUPPORTED_EXTENSIONS
from backend.core.errors import FileError, ParseError
from backend.rag.cleaner import clean_text

_HEADING_MD = re.compile(r"^#{1,6}\s+\S")
_HEADING_CN = re.compile(r"^第[一二三四五六七八九十百零\d]+[章节条款部分]\s*\S")
_HEADING_NUM = re.compile(r"^\d+(\.\d+){0,3}[\s、.]\s*\S")
_HEADING_CN_NUM = re.compile(r"^[一二三四五六七八九十]+[、.]\s*\S")
_MAX_BLOCK_CHARS = 700


@dataclass
class ParsedBlock:
    text: str
    section: str | None = None
    page: int | None = None


@dataclass
class ParsedDocument:
    blocks: list[ParsedBlock] = field(default_factory=list)
    parser: str = ""

    @property
    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


def is_heading(line: str) -> bool:
    """识别 Markdown 标题、中文条款标题与数字编号标题。"""
    s = line.strip()
    if len(s) > 60 or not s:
        return False
    return bool(
        _HEADING_MD.match(s)
        or _HEADING_CN.match(s)
        or _HEADING_NUM.match(s)
        or _HEADING_CN_NUM.match(s)
    )


def _clean_heading(line: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", line.strip()).strip()


def _group_lines(lines: list[str], page: int | None = None) -> list[ParsedBlock]:
    """按标题切段，标题行并入其所属段落，保证检索片段自带章节信息。"""
    blocks: list[ParsedBlock] = []
    section = "文档开头"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = clean_text("\n".join(buffer))
        if text:
            blocks.append(ParsedBlock(text=text, section=section, page=page))
        buffer = []

    for raw in lines:
        line = raw.strip()
        if not line:
            if buffer:
                flush()
            continue
        if is_heading(line):
            if buffer:
                flush()
            section = _clean_heading(line)
            buffer = [line]
            continue
        buffer.append(line)
        if sum(len(x) + 1 for x in buffer) >= _MAX_BLOCK_CHARS:
            flush()
    if buffer:
        flush()
    return blocks


def _parse_txt_md(path: Path) -> tuple[list[ParsedBlock], str]:
    raw = None
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            raw = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise ParseError("文本编码无法识别", "请使用 UTF-8 或 GBK 编码的文件")
    return _group_lines(raw.splitlines()), "纯文本/Markdown 解析器"


def _parse_pdf(path: Path) -> tuple[list[ParsedBlock], str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ParseError("缺少 PDF 解析组件", "请先安装 pypdf") from exc
    try:
        reader = PdfReader(str(path))
        blocks: list[ParsedBlock] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            blocks.extend(_group_lines(text.splitlines(), page=index))
        return blocks, "pypdf 逐页解析器"
    except Exception as exc:
        raise ParseError("PDF 解析失败", str(exc)) from exc


def _parse_docx(path: Path) -> tuple[list[ParsedBlock], str]:
    try:
        from docx import Document
    except ImportError as exc:
        raise ParseError("缺少 DOCX 解析组件", "请先安装 python-docx") from exc
    try:
        doc = Document(str(path))
        lines: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "") if para.style else ""
            if style.lower().startswith("heading"):
                lines.append("## " + text)
            else:
                lines.append(text)
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
        return _group_lines(lines), "python-docx 段落与表格解析器"
    except Exception as exc:
        raise ParseError("DOCX 解析失败", str(exc)) from exc


def parse_file(path: Path, filename: str | None = None) -> ParsedDocument:
    """统一入口：校验类型与空文件，返回带章节/页码的解析结果。"""
    name = filename or path.name
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FileError(
            f"不支持的文件类型：{ext or '无扩展名'}",
            "仅支持 PDF、DOCX、TXT、MD 四种格式",
        )
    if not path.exists():
        raise FileError("文件不存在", str(path))
    if path.stat().st_size == 0:
        raise FileError("文件内容为空", f"文件 {name} 大小为 0 字节")

    dispatch = {
        ".pdf": _parse_pdf,
        ".docx": _parse_docx,
        ".txt": _parse_txt_md,
        ".md": _parse_txt_md,
    }
    blocks, parser_name = dispatch[ext](path)
    blocks = [b for b in blocks if b.text.strip()]
    if not blocks or not "\n".join(b.text for b in blocks).strip():
        raise ParseError(
            "未能从文件中提取到有效文本",
            "若为扫描版 PDF，请先进行 OCR 后重新上传",
        )
    return ParsedDocument(blocks=blocks, parser=parser_name)
