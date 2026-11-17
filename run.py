"""一键启动脚本：同时启动 FastAPI 后端与 Streamlit 前端。

用法：python run.py
分别启动：python run.py backend / python run.py frontend
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def start_backend() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "backend.main:app",
            "--host", "127.0.0.1", "--port", "8000",
        ],
        cwd=str(ROOT),
    )


def start_frontend() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "frontend/app.py",
            "--server.address", "127.0.0.1", "--server.port", "8501",
            "--server.headless", "true",
        ],
        cwd=str(ROOT),
    )


def main() -> None:
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    processes: list[subprocess.Popen] = []
    if mode in ("all", "backend"):
        processes.append(start_backend())
        print("后端已启动：http://127.0.0.1:8000 （接口文档 /docs）")
    if mode in ("all", "frontend"):
        processes.append(start_frontend())
        print("前端已启动：http://127.0.0.1:8501")
    if not processes:
        print("用法：python run.py [all|backend|frontend]")
        return
    print("按 Ctrl+C 停止服务。")
    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()
        print("服务已停止。")


if __name__ == "__main__":
    main()
