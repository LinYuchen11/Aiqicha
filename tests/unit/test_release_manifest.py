"""第二轮打包回归测试：白名单不得漏掉源码包，也不得放进密钥/缓存/数据库。

背景：初版 build_release.py 把 `models` 放进「任意层级排除」，
误伤了源码包 backend/models/（Pydantic 契约 schemas.py），
导致解压后的交付包出现 ModuleNotFoundError: No module named 'backend.models'。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_release.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_release_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_source_python_files_are_included():
    """backend / frontend / scripts / tests 下所有 .py 源码都必须进交付包。"""
    mod = _load_module()
    excluded = []
    for package in ("backend", "frontend", "scripts", "tests"):
        for path in (ROOT / package).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if not mod._allowed(path):
                excluded.append(str(path.relative_to(ROOT)))
    assert excluded == [], f"以下源码会被漏打包，交付包将无法运行：{excluded}"


def test_backend_models_package_is_included():
    """models/ 是顶层模型缓存，不能误伤 backend/models 源码包。"""
    mod = _load_module()
    for rel in ("backend/models/__init__.py", "backend/models/schemas.py"):
        path = ROOT / rel
        assert path.exists(), f"源码文件缺失：{rel}"
        assert mod._allowed(path), f"源码包被误排除：{rel}"


def test_sensitive_and_runtime_artifacts_are_excluded():
    """密钥、数据库、缓存、虚拟环境、平台数据、顶层模型缓存不得打包。"""
    mod = _load_module()
    blocked = [
        ".env",
        "data/knowledge_agent.db",
        "data/uploads/用户上传.pdf",
        "backend/__pycache__/config.cpython-313.pyc",
        ".pytest_cache/v/cache/lastfailed",
        ".venv/Scripts/python.exe",
        ".workbuddy/memory/2026-11-16.md",
        "models/bge-small-zh-v1.5/config.json",
        "dist/Enterprise-Knowledge-Agent-v2.zip",
    ]
    leaked = [rel for rel in blocked if mod._allowed(ROOT / rel)]
    assert leaked == [], f"以下敏感/运行产物会被误打包：{leaked}"


def test_required_deliverables_are_included():
    """关键交付物必须存在且允许打包。"""
    mod = _load_module()
    required = [
        "README.md", ".env.example", ".gitignore", "run.py",
        "requirements.txt", "requirements-optional.txt", "requirements.lock.txt",
        "docs/evaluation_report.md", "docs/agent_evaluation_report.md",
        "docs/deepseek_verification.md",
        "docs/screenshots/01_智能助手.png",
        "data/sample_docs/1_企业考勤与请假管理制度.md",
        "data/evaluation/agent_questions.json",
    ]
    problems = []
    for rel in required:
        path = ROOT / rel
        if not path.exists() or not mod._allowed(path):
            problems.append(rel)
    assert problems == [], f"关键交付物缺失或被排除：{problems}"
