"""知识库管理接口：上传、列表、详情、删除、重新处理。"""
from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from backend.core.errors import ParamError
from backend.services import document_service

router = APIRouter(prefix="/api/documents", tags=["知识库管理"])


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict:
    if not files:
        raise ParamError("请选择要上传的文件", "支持 PDF、DOCX、TXT、MD，可多选")
    payload = [(file.filename or "未命名文件", await file.read()) for file in files]
    return document_service.process_uploads(payload)


@router.get("")
def list_documents() -> dict:
    return document_service.overview()


@router.get("/{doc_id}")
def document_detail(doc_id: str) -> dict:
    return document_service.document_detail(doc_id)


@router.get("/{doc_id}/chunks")
def document_chunks(doc_id: str) -> dict:
    return {"文本块": document_service.document_detail(doc_id)["文本块"]}


@router.post("/{doc_id}/reprocess")
def reprocess(doc_id: str, chunk_size: int | None = None, overlap: int | None = None) -> dict:
    return document_service.reprocess_document(doc_id, chunk_size, overlap)


@router.delete("/{doc_id}")
def delete(doc_id: str) -> dict:
    return document_service.delete_document(doc_id)
