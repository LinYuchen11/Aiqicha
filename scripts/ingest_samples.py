"""仅重新导入/补齐模拟企业文档（按内容哈希去重，不会重复写入）。

用法：python scripts/ingest_samples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.db import init_database  # noqa: E402
from backend.services.document_service import ensure_sample_documents  # noqa: E402


def main() -> None:
    init_database()
    result = ensure_sample_documents()
    print(
        f"模拟企业文档同步完成：新导入 {result['已导入']} 份，"
        f"内容变更已重建 {result['已更新']} 份，未变化 {result['已存在']} 份，"
        f"共 {result['文档总数']} 份。"
    )


if __name__ == "__main__":
    main()
