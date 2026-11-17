"""全局配置：所有敏感项从环境变量读取，密钥不写入代码、不进入日志。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)

# 国内直连 huggingface.co 常不可达；允许通过 .env 指定镜像，保证本地模型下载流程可用。
# 使用 setdefault，不覆盖用户已在系统环境变量中设置的值。
_HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com").strip()
if _HF_ENDPOINT:
    os.environ.setdefault("HF_ENDPOINT", _HF_ENDPOINT)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _path(name: str, default: str) -> Path:
    raw = _env(name, default)
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@dataclass(frozen=True)
class Settings:
    project_root: Path
    db_path: Path
    upload_dir: Path
    vector_dir: Path
    sample_dir: Path
    eval_dir: Path

    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    llm_mode_raw: str
    llm_timeout: int
    llm_max_tokens: int

    embedding_mode: str
    embedding_model: str
    hf_endpoint: str
    vector_store: str
    chroma_persist_dir: Path

    chunk_size: int
    chunk_overlap: int
    default_top_k: int
    hybrid_weight: float
    rerank_mode: str

    api_host: str
    api_port: int
    api_base_url: str
    max_file_size_mb: int

    @property
    def llm_mode(self) -> str:
        """auto：未配置 Key 时自动降级为 mock，保证零配置可运行。"""
        if self.llm_mode_raw == "mock" or not self.deepseek_api_key:
            return "mock"
        return "deepseek"

    @property
    def is_mock(self) -> bool:
        return self.llm_mode == "mock"

    def public_dict(self) -> dict:
        """可安全下发前端的配置快照（绝不包含密钥内容）。"""
        return {
            "运行模式": self.llm_mode,
            "模型名称": self.deepseek_model if not self.is_mock else "本地抽取式模拟器（非真实大模型）",
            "接口地址": self.deepseek_base_url if not self.is_mock else "未调用外部接口",
            "密钥已配置": bool(self.deepseek_api_key),
            "向量方案": self.embedding_mode,
            "正式演示推荐档位": "local（BAAI/bge-small-zh-v1.5）",
            "向量模型": self.embedding_model if self.embedding_mode == "local" else "内置词面哈希向量（离线备用，非语义 Embedding）",
            "模型下载镜像": self.hf_endpoint or "未配置（直连 huggingface.co）",
            "向量库": self.vector_store,
            "分块大小": self.chunk_size,
            "分块重叠": self.chunk_overlap,
            "默认召回数": self.default_top_k,
            "混合检索权重": self.hybrid_weight,
            "重排序": self.rerank_mode,
        }


def build_settings() -> Settings:
    return Settings(
        project_root=PROJECT_ROOT,
        db_path=_path("DB_PATH", "./data/knowledge_agent.db"),
        upload_dir=_path("UPLOAD_DIR", "./data/uploads"),
        vector_dir=PROJECT_ROOT / "data" / "vector_db",
        sample_dir=PROJECT_ROOT / "data" / "sample_docs",
        eval_dir=PROJECT_ROOT / "data" / "evaluation",
        deepseek_api_key=_env("DEEPSEEK_API_KEY"),
        deepseek_base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
        llm_mode_raw=_env("LLM_MODE", "auto").lower(),
        llm_timeout=_int("LLM_TIMEOUT", 60),
        llm_max_tokens=_int("LLM_MAX_TOKENS", 1500),
        embedding_mode=_env("EMBEDDING_MODE", "hash").lower(),
        embedding_model=_env("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        hf_endpoint=_HF_ENDPOINT,
        vector_store=_env("VECTOR_STORE", "sqlite").lower(),
        chroma_persist_dir=_path("CHROMA_PERSIST_DIR", "./data/vector_db/chroma"),
        chunk_size=max(80, _int("CHUNK_SIZE", 400)),
        chunk_overlap=max(0, _int("CHUNK_OVERLAP", 80)),
        default_top_k=_int("DEFAULT_TOP_K", 5),
        hybrid_weight=min(1.0, max(0.0, _float("HYBRID_WEIGHT", 0.6))),
        rerank_mode=_env("RERANK_MODE", "none").lower(),
        api_host=_env("API_HOST", "127.0.0.1"),
        api_port=_int("API_PORT", 8000),
        api_base_url=_env("API_BASE_URL", "http://127.0.0.1:8000"),
        max_file_size_mb=_int("MAX_FILE_SIZE_MB", 10),
    )


settings = build_settings()
