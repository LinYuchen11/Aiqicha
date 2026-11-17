"""FastAPI 应用入口：中文错误响应、启动时初始化数据库与模拟企业知识库。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import api_router
from backend.core.config import settings
from backend.core.errors import AppError
from backend.core.log_utils import get_logger, setup_logging
from backend.database.db import init_database
from backend.services.document_service import ensure_sample_documents

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_database()
    result = ensure_sample_documents()
    logger.info("服务启动完成，模拟文档导入结果：%s", result)
    logger.info("运行模式：%s；向量档位：%s", settings.llm_mode, settings.embedding_mode)
    yield


app = FastAPI(
    title="通用企业级智能知识管理与任务助手",
    description="企业级 RAG + LangGraph Agent 智能知识助手后端接口（全中文提示）",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"错误": exc.to_dict()})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = "；".join(
        f"{'.'.join(str(x) for x in error.get('loc', ()))}：{error.get('msg', '参数不合法')}"
        for error in exc.errors()
    )
    return JSONResponse(
        status_code=400,
        content={"错误": {"错误类型": "参数校验失败", "错误信息": "请求参数不合法", "详细说明": details}},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理的异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"错误": {"错误类型": "系统内部错误", "错误信息": "服务处理异常，请稍后重试", "详细说明": str(exc)[:300]}},
    )


@app.get("/", tags=["系统状态"])
def root() -> dict:
    return {
        "系统名称": "通用企业级智能知识管理与任务助手",
        "状态": "后端服务运行正常",
        "接口文档": "/docs",
        "健康检查": "/api/health",
    }
