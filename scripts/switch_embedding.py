"""切换 Embedding 档位并自动重建向量库，避免不同模型向量混用。

用法：
    python scripts/switch_embedding.py local    # 正式演示推荐：本地 BGE 语义向量
    python scripts/switch_embedding.py hash    # 离线备用：词面哈希向量（非语义 Embedding）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.config import settings  # noqa: E402
from backend.database.db import init_database  # noqa: E402
from backend.rag import model_guard  # noqa: E402
from backend.rag.embeddings import embedding_info, reset_embedder  # noqa: E402
from backend.services import document_service  # noqa: E402

ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"


def _write_env(mode: str) -> None:
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    else:
        lines = EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
        print("未找到 .env，已按 .env.example 创建。")
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith("EMBEDDING_MODE="):
            lines[index] = f"EMBEDDING_MODE={mode}"
            replaced = True
            break
    if not replaced:
        lines.append(f"EMBEDDING_MODE={mode}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    mode = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
    if mode not in {"local", "hash"}:
        print("用法：python scripts/switch_embedding.py local|hash")
        print("  local = 正式演示推荐（本地 BGE 语义向量，需可选依赖）")
        print("  hash  = 离线备用（词面哈希向量，非语义 Embedding，零下载）")
        return

    _write_env(mode)
    # 同一进程内让新档位立即生效，再走真实重建链路
    object.__setattr__(settings, "embedding_mode", mode)
    reset_embedder()
    init_database()

    info = embedding_info()
    print(f"配置档位：{info['配置档位']}｜实际档位：{info['实际档位']}")
    print(f"实际模型：{info['模型名称']}｜维度：{info['向量维度']}")
    if info["降级原因"] != "无":
        print(f"⚠️ 模型未生效，已降级：{info['降级原因']}")
        print("提示：请执行 python -m pip install -i https://pypi.org/simple -r requirements-optional.txt")

    result = document_service.reconcile_vector_model()
    if result["已重建"]:
        print(
            f"向量库已重建（{result['原因']}）：成功 {result['重建文档数']} 份，"
            f"失败 {result['失败文档数']} 份。"
        )
    else:
        print(f"向量库无需重建：{result['原因']}。")

    status = model_guard.compatibility_status("default")
    print(f"最终校验：{status['提示']}｜向量数 {status['向量数']}｜库内模型 {status['库内模型']}")
    if not info["是否语义向量"]:
        print("说明：hash 档是词面哈希向量，不是语义 Embedding，仅作离线备用。")


if __name__ == "__main__":
    main()
