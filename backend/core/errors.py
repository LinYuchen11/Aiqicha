"""统一异常体系：所有错误信息为中文，便于 API 层直接返回给用户。"""
from __future__ import annotations


class AppError(Exception):
    code = "系统内部错误"
    status = 500

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"错误类型": self.code, "错误信息": self.message, "详细说明": self.detail}


class ParamError(AppError):
    code = "参数校验失败"
    status = 400


class NotFoundError(AppError):
    code = "资源不存在"
    status = 404


class DuplicateError(AppError):
    code = "文件重复"
    status = 409


class FileError(AppError):
    code = "文件处理失败"
    status = 400


class ParseError(FileError):
    code = "文档解析失败"


class VectorError(AppError):
    code = "向量库异常"


class LLMError(AppError):
    code = "大模型调用失败"
    status = 502


class ToolError(AppError):
    code = "工具执行失败"
    status = 400


class DBError(AppError):
    code = "数据库读写异常"


class ConfigError(AppError):
    code = "配置错误"
    status = 500
