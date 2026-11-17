"""数据库初始化脚本：建表 + 导入预置模拟企业文档。

用法：python scripts/init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.config import settings  # noqa: E402
from backend.database.db import init_database  # noqa: E402
from backend.services.document_service import ensure_sample_documents  # noqa: E402


def main() -> None:
    init_database()
    print(f"数据库初始化完成：{settings.db_path}")
    result = ensure_sample_documents()
    print(
        f"模拟企业文档：新导入 {result['已导入']} 份，内容变更已重建 {result['已更新']} 份，"
        f"未变化 {result['已存在']} 份，目录内共 {result['文档总数']} 份。"
    )


if __name__ == "__main__":
    main()
