"""重建生产向量库：用于模型指纹缺失、切换模型后异常、或需要全量刷新时。

用法：
    python scripts/rebuild_vectors.py            # 仅当模型来源缺失/不一致时重建
    python scripts/rebuild_vectors.py --force   # 无条件按原始文件全量重建
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import document_repo  # noqa: E402
from backend.database.db import init_database  # noqa: E402
from backend.rag import model_guard  # noqa: E402
from backend.rag.embeddings import embedding_info  # noqa: E402
from backend.rag.vectorstore import get_vector_store  # noqa: E402
from backend.services import document_service  # noqa: E402

COLLECTION = "default"


def main() -> None:
    parser = argparse.ArgumentParser(description="按原始文件重建生产向量库（中文输出）")
    parser.add_argument("--force", action="store_true", help="无条件全量重建")
    args = parser.parse_args()

    init_database()
    info = embedding_info()
    print(f"当前实际 Embedding：{info['模型名称']}｜{info['向量维度']} 维｜档位 {info['实际档位']}")
    if info["降级原因"] != "无":
        print(f"模型降级原因：{info['降级原因']}")

    if args.force:
        get_vector_store().delete_collection(COLLECTION)
        model_guard.clear_meta(COLLECTION)
        rebuilt, failed = 0, []
        for doc in document_repo.list_documents():
            try:
                document_service.reprocess_document(doc["id"])
                rebuilt += 1
            except Exception as exc:
                message = getattr(exc, "message", None) or str(exc)
                failed.append(f"{doc['filename']}：{message}")
                document_repo.update_document(doc["id"], status="失败", error_msg=message)
        print(f"全量重建完成：成功 {rebuilt} 份，失败 {len(failed)} 份。")
        for item in failed:
            print(f"  失败：{item}")
    else:
        result = document_service.reconcile_vector_model(COLLECTION)
        if result["已重建"]:
            print(
                f"已按模型指纹触发重建（{result['原因']}）："
                f"成功 {result['重建文档数']} 份，失败 {result['失败文档数']} 份。"
            )
            for item in result["失败明细"]:
                print(f"  失败：{item}")
        else:
            print(f"无需重建：{result['原因']}。")

    status = model_guard.compatibility_status(COLLECTION)
    print(f"校验结果：{status['提示']}｜库内模型 {status['库内模型']}｜向量数 {status['向量数']}")


if __name__ == "__main__":
    main()
