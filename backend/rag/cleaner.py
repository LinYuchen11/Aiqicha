"""文本清洗与中文检索分词。解析、分块、Embedding、关键词检索共用本模块。"""
from __future__ import annotations

import re

_CONTROL_KEEP = {"\n", "\t"}
_NOISE_LINES = (
    r"^第\s*\d+\s*页(\s*/?\s*共\s*\d+\s*页)?$",
    r"^\s*[-=—_·]{4,}\s*$",
    r"^\s*page\s+\d+\s*(of\s+\d+)?\s*$",
    r"^\s* confidential \s*$",
)
_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[a-z0-9]+")


def clean_text(text: str) -> str:
    """清除控制字符、页眉页脚、重复空白，保留换行以维持段落结构。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    text = "".join(ch for ch in text if ch in _CONTROL_KEEP or ord(ch) >= 32)
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = re.sub(r"[ \t\u3000]+", " ", raw_line).strip()
        if not line:
            lines.append("")
            continue
        if any(re.match(pattern, line, re.IGNORECASE) for pattern in _NOISE_LINES):
            continue
        lines.append(line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r" {2,}", " ", out)
    return out.strip()


def normalize_query(text: str) -> str:
    """用户输入归一：去控制字符、压缩空白、限长。"""
    text = "".join(ch for ch in (text or "") if ch in _CONTROL_KEEP or ord(ch) >= 32)
    return re.sub(r"\s+", " ", text).strip()


def tokenize_for_search(text: str) -> list[str]:
    """中文按单字 + 相邻二元字组，英文数字按词切分。供哈希向量与 BM25 共用。"""
    normalized = normalize_query(text).lower()
    tokens: list[str] = []
    tokens.extend(_WORD_RE.findall(normalized))
    han = _HAN_RE.findall(normalized)
    tokens.extend(han)
    tokens.extend(han[i] + han[i + 1] for i in range(len(han) - 1))
    return tokens


def keyword_overlap(query: str, text: str) -> float:
    """查询词在文本中的覆盖率，用于规则式重排序。"""
    q = set(tokenize_for_search(query))
    if not q:
        return 0.0
    t = set(tokenize_for_search(text))
    return len(q & t) / len(q)
