"""测试夹具：每个用例使用独立临时 SQLite，避免污染运行时数据；全部使用 Mock 模型。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.config import settings  # noqa: E402
from backend.database import db as db_module  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """重定向数据库与上传目录到临时路径，并重建表结构。"""
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "upload_dir", tmp_path / "uploads")
    object.__setattr__(settings, "vector_dir", tmp_path / "vector_db")
    db_module._initialized = False
    db_module.init_database()
    yield


@pytest.fixture
def sample_markdown(tmp_path) -> Path:
    path = tmp_path / "模拟考勤制度.md"
    path.write_text(
        "> 本文件为模拟企业制度文档，仅用于测试。\n\n"
        "## 一、年假申请规定\n"
        "员工申请年假需提前 3 个工作日提交申请，由部门负责人在 2 个工作日内审批。"
        "工作满 1 年不满 5 年的员工每年享有 5 天年假，满 5 年享有 10 天年假。\n\n"
        "## 二、加班与调休规定\n"
        "加班需提前在系统登记，调休应在加班发生后 30 天内使用，逾期未使用自动失效。\n\n"
        "## 三、考勤异常处理\n"
        "忘打卡需在 2 个工作日内提交补卡申请，每月补卡不得超过 3 次。\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def api_client(isolated_db, monkeypatch):
    """FastAPI TestClient：阻止启动时自动导入真实样本文档，保证用例可控。"""
    monkeypatch.setattr(
        "backend.main.ensure_sample_documents",
        lambda: {"已导入": 0, "已存在": 0, "文档总数": 0},
    )
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        yield client
