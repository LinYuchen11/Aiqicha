"""预置模拟文档同步：磁盘内容修改后应原地重建，不产生同名旧记录。"""
from __future__ import annotations

import pytest

from backend.core.config import settings
from backend.database import document_repo
from backend.rag.vectorstore import get_vector_store
from backend.services import document_service


@pytest.fixture
def sample_dir(tmp_path):
    """把样本文档目录指向临时目录，用例结束后恢复。"""
    target = tmp_path / "samples"
    target.mkdir()
    original = settings.sample_dir
    object.__setattr__(settings, "sample_dir", target)
    yield target
    object.__setattr__(settings, "sample_dir", original)


def test_modified_sample_document_is_reprocessed_in_place(sample_dir):
    path = sample_dir / "制度.md"
    path.write_text("# 年假制度\n旧版年假为 5 天，需提前三天申请。\n", encoding="utf-8")

    first = document_service.ensure_sample_documents()
    assert first["已导入"] == 1
    assert first["文档总数"] == 1
    docs = document_repo.list_documents()
    assert len(docs) == 1
    doc_id = docs[0]["id"]
    old_sha = docs[0]["sha256"]

    path.write_text("# 年假制度\n新版年假为 15 天，试用期内不适用该规定。\n", encoding="utf-8")
    second = document_service.ensure_sample_documents()

    assert second["已导入"] == 0
    assert second["已更新"] == 1
    assert second["文档总数"] == 1
    docs2 = document_repo.list_documents()
    assert len(docs2) == 1, "内容变化不得插入第二条同名文档记录"
    assert docs2[0]["id"] == doc_id
    assert docs2[0]["sha256"] != old_sha

    records = get_vector_store().list_records("default")
    all_text = "\n".join(item.text for item in records)
    assert "新版年假为 15 天" in all_text
    assert "旧版年假为 5 天" not in all_text, "旧向量必须被清除"

    third = document_service.ensure_sample_documents()
    assert third["已导入"] == 0
    assert third["已更新"] == 0
    assert third["已存在"] == 1, "幂等：内容未变时不再重建"


def test_reprocess_from_ui_syncs_fingerprint(sample_dir):
    """界面点「重新处理该文档」后，重启后端不应再把它当成新文档。"""
    path = sample_dir / "报销制度.md"
    path.write_text("# 报销制度\n交通费每月上限 300 元。\n", encoding="utf-8")
    document_service.ensure_sample_documents()
    doc = document_repo.list_documents()[0]

    path.write_text("# 报销制度\n交通费每月上限 800 元，需附发票。\n", encoding="utf-8")
    result = document_service.reprocess_document(doc["id"])
    assert result["状态"] == "已完成"

    refreshed = document_repo.get_document(doc["id"])
    assert refreshed["sha256"] != doc["sha256"]
    assert "800 元" in "\n".join(r.text for r in get_vector_store().list_records("default"))

    again = document_service.ensure_sample_documents()
    assert again["已更新"] == 0
    assert again["已存在"] == 1
    assert len(document_repo.list_documents()) == 1
