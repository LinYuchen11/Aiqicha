"""日志工具：对形如 sk-xxx 的密钥做脱敏，保证密钥不出现在日志中。"""
from __future__ import annotations

import logging
import re

_KEY_RE = re.compile(r"(sk-[A-Za-z0-9]{4})[A-Za-z0-9_\-]{4,}")
_configured = False


class _MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = _KEY_RE.sub(r"\1****", str(record.msg))
            if isinstance(record.args, tuple):
                # 只脱敏字符串参数；保留数字等原类型，避免破坏 %d 等格式化
                record.args = tuple(
                    _KEY_RE.sub(r"\1****", arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        except Exception:
            pass
        return True


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    handler.addFilter(_MaskFilter())
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
