"""生成干净的作品集交付 ZIP：白名单控制，排除密钥、数据库、缓存与上传产物。

用法：python scripts/build_release.py
输出：dist/Enterprise-Knowledge-Agent-v2.zip
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "dist"
ZIP_PATH = OUTPUT_DIR / "Enterprise-Knowledge-Agent-v2.zip"

# 顶层允许打包的条目
INCLUDE_TOP = {
    ".env.example", ".gitignore", "README.md", "run.py",
    "requirements.txt", "requirements-optional.txt", "requirements.lock.txt",
    "backend", "frontend", "scripts", "tests", "docs", "data",
}
# 任意层级都要排除的目录名
EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".venv", "venv", ".git", ".idea", ".vscode",
    ".streamlit", ".workbuddy", "dist", "release", ".cache", "logs", "results",
}
# 仅顶层排除：本地模型缓存目录。
# 注意：`models` 不能放进 EXCLUDE_DIRS（任意层级），否则会误伤源码包
# backend/models/（Pydantic 契约 schemas.py），导致交付包无法启动。
TOP_ONLY_EXCLUDE_DIRS = {"models"}
# 任意层级都要排除的文件名/后缀
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".zip", ".log"}


def _allowed(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
        return False
    if rel.parts and rel.parts[0] in TOP_ONLY_EXCLUDE_DIRS:
        return False
    if rel.parts and rel.parts[0] not in INCLUDE_TOP:
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    if path.name == ".env" or path.name.endswith(".env.local"):
        return False
    # 上传副本与向量库缓存不打包，但保留 .gitkeep 占位
    if "uploads" in rel.parts or "vector_db" in rel.parts:
        return path.name == ".gitkeep"
    return True


def main() -> None:
    files = sorted(
        (path for path in ROOT.rglob("*") if path.is_file() and _allowed(path)),
        key=lambda item: str(item.relative_to(ROOT)).lower(),
    )
    if not files:
        raise SystemExit("没有找到可打包的源文件，请检查白名单配置。")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, Path(ROOT.name) / path.relative_to(ROOT))
    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    print(f"已生成：{ZIP_PATH}")
    print(f"文件数：{len(files)}｜大小：{size_mb:.2f} MB")
    print("\n顶层目录：")
    tops: dict[str, int] = {}
    for path in files:
        key = path.relative_to(ROOT).parts[0]
        tops[key] = tops.get(key, 0) + 1
    for key in sorted(tops):
        print(f"  {key}: {tops[key]} 个文件")
    print("\n已排除：.env / *.db / __pycache__ / .pyc / .pytest_cache / .venv / "
          "data/uploads / data/vector_db / *.zip / .workbuddy / 模型缓存")


if __name__ == "__main__":
    main()
