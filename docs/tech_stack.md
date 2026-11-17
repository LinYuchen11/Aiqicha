# 技术选型说明

## 一、选型表

| 领域 | 选型 | 原因 | 对应代码 |
| --- | --- | --- | --- |
| 大模型 | DeepSeek API（OpenAI 兼容协议） | 中文能力强、成本低、兼容 JSON 结构化输出与流式 | `backend/llm/client.py` |
| 后端 | Python 3.13 + FastAPI + Uvicorn | 轻量、类型友好、自动生成接口文档 | `backend/main.py`、`backend/api/` |
| Agent 框架 | LangGraph 1.x + langchain-core | 显式状态图与条件分支，可解释、可持久化；避免把大模型包成聊天机器人 | `backend/agent/graph.py` |
| Embedding（开箱默认，离线备用） | `hash`：内置**词面哈希向量**（字符 unigram + bigram 的 blake2b 分桶、log1p、L2 归一化，256 维） | 免费、零模型下载、纯本地、可复现；**仅匹配字面重合，不是语义 Embedding**，只用于「只装默认依赖」也能跑通离线备用与链路演示 | `backend/rag/embeddings.py::HashEmbedder` |
| Embedding（正式演示推荐档） | `local`：BAAI/bge-small-zh-v1.5（sentence-transformers） | 免费开源中文**语义**向量，是正式演示推荐档位（`RECOMMENDED_MODE = "local"`）；需可选依赖与模型下载 | `backend/rag/embeddings.py::LocalEmbedder` |
| 模型指纹与向量重建 | `model_guard.py` + `embedding_meta` 表 | 不同模型向量禁止混用；写入后登记、检索前校验、切换模型强制重建 | `backend/rag/model_guard.py`、`backend/database/schema.py`、`services/document_service.py` |
| 向量库（默认） | SQLite 向量表 + numpy 余弦 | 与业务数据同库、重启即持久化、零额外服务 | `backend/rag/vectorstore.py::SqliteVectorStore` |
| 向量库（可选） | Chroma | 社区常用、持久化方便，接口与默认实现一致 | `backend/rag/vectorstore.py::ChromaVectorStore` |
| 业务数据库 | SQLite | 单机零配置，覆盖文档/会话/工单/日志/实验与 `embedding_meta` | `backend/database/` |
| 关键词检索 | 自实现 BM25 | 无需额外服务，与向量分归一化后加权混合 | `backend/rag/retriever.py::_bm25` |
| 重排序 | `none` 默认关闭 / `rule` 规则式（确定性打分，非模型）/ `local` 真实 CrossEncoder（BAAI/bge-reranker-base） | 规则式可解释、零成本；模型重排一次批量 `predict`，不可用时显式降级并标注 | `backend/rag/rerank.py` |
| 前端 | Streamlit + Plotly | 中文多页面快速交付、图表交互直观 | `frontend/` |
| 参数校验 | Pydantic v2 | 请求体与工具参数统一校验，错误中文可读 | `backend/models/`、`backend/tools/schemas.py` |
| 测试 | pytest | 单元测试与集成测试覆盖业务场景 | `tests/` |

## 二、Embedding 双档与模型指纹（第二轮）

### 2.1 档位定位

| 档位 | 定位 | 是否语义向量 | 依赖 | 维度 |
| --- | --- | --- | --- | --- |
| `hash`（默认） | **词面哈希向量，非语义 Embedding，离线备用** | 否 | 仅默认依赖（numpy） | 256 |
| `local` | **正式演示推荐档位**：BAAI/bge-small-zh-v1.5 本地 BGE 语义向量 | 是 | `requirements-optional.txt`（sentence-transformers / torch） | 由模型决定 |

- **开箱默认仍是 `hash`**（`config.py` 中 `EMBEDDING_MODE` 默认 `hash`，`.env.example` 同样写死 `hash`），目的是保证「只装默认依赖」就能跑通文档解析 → 分块 → 向量化 → 混合检索 → 评估的完整链路，零下载、零费用。
- `local` 是 `embeddings.py::RECOMMENDED_MODE` 与 `config.py::Settings.public_dict()` 中标注的「正式演示推荐档位」，但**不是默认值**。切换方式：`python scripts/switch_embedding.py local`（脚本会写 `.env`、重置单例并自动重建向量库）。
- `local` 在依赖缺失、模型下载失败或加载失败时**降级为 `hash`** 并记录 `降级原因`，`embedding_info()` 如实返回「实际档位 / 是否语义向量 / 降级原因」，前端侧边栏显示「配置档位 / 实际档位 / 模型名称 / 向量维度」并在非语义时提示。
- `HF_ENDPOINT`：`config.py` 默认设为 `https://hf-mirror.com`（国内镜像），用 `os.environ.setdefault` 生效，**不覆盖用户已在系统环境变量中设置的值**；`.env.example` 中亦提供该项，留空则直连 huggingface.co。

### 2.2 模型指纹表 `embedding_meta`

`backend/database/schema.py` 中的 `embedding_meta(collection, model_key, model_name, dim, effective_mode, updated_at)` 为每个向量集合记录「由哪个 Embedding 模型生成」。`model_key` 形如 `hash:256` 或 `local:BAAI/bge-small-zh-v1.5:维度`（`embeddings.py::embedding_fingerprint`）。

| 动作 | 函数 | 行为 |
| --- | --- | --- |
| 写入向量后登记 | `model_guard.mark_written` | 校验本批向量维度一致，再 upsert 指纹记录 |
| 检索前校验 | `model_guard.assert_compatible` | 集合非空但来源缺失，或模型不一致 → 抛中文 `VectorError`，**绝不静默降级为关键词检索** |
| 只读状态 | `model_guard.compatibility_status` | 供 `/api/health` 的「向量库一致性」与前端侧边栏使用 |
| 切换模型后重建 | `document_service.reconcile_vector_model` | 指纹不一致时清空集合，按原始文件逐文档 `reprocess_document` 重建 |

BGE 语义向量与 CrossEncoder 模型重排实验在本次环境中**均未运行**（可选依赖安装超过 29 分钟无进展已主动停止），`docs/evaluation_report.md` 的「未运行说明」为最终准绳；本文件只说明已实现的能力，不声称模型实验已跑出结果。

## 三、运维脚本

| 脚本 | 用途 |
| --- | --- |
| `scripts/switch_embedding.py` | 切换 Embedding 档位（`local` / `hash`）：写 `.env`、`reset_embedder()`、调用 `reconcile_vector_model()` 自动重建并校验指纹 |
| `scripts/rebuild_vectors.py` | 重建生产向量库：默认仅在指纹缺失/不一致时重建，`--force` 无条件按原始文件全量重建 |
| `scripts/verify_deepseek.py` | 真实 DeepSeek API 8 项检查；未配置 `DEEPSEEK_API_KEY`（或处于 Mock 模式）时输出「真实 DeepSeek API 未验证」，8 项全部记为「未验证」，不改写报告、不写模拟通过结果 |
| `scripts/capture_screenshots.py` | 用无头浏览器为 5 个 Streamlit 页面截图；校验图片真实渲染成功，仅保留成功图片，失败如实报错、不生成占位图 |
| `scripts/run_evaluation.py` | 真实运行 5 组 RAG 实验并生成 `docs/evaluation_report.md`，不填充虚构数据 |
| `scripts/run_agent_evaluation.py` | 真实逐题调用 `chat_service.chat()` 聚合 Agent 专项四项指标，生成 `docs/agent_evaluation_report.md`，评估对象为 Mock 规则决策器 |
| `scripts/init_db.py`、`scripts/ingest_samples.py` | 初始化数据库、导入样例文档 |

## 四、免费 / 付费边界（重要）

| 类别 | 组件 | 说明 |
| --- | --- | --- |
| 免费开源软件 | FastAPI、LangGraph、langchain-core、Streamlit、Plotly、pypdf、python-docx、numpy、pandas、pytest、SQLite | 默认 `requirements.txt` 全部包含 |
| 需要下载的本地模型（免费但需下载） | bge-small-zh-v1.5、bge-reranker-base、torch、sentence-transformers、Chroma | 放在 `requirements-optional.txt`，**默认不安装**，不影响基础功能 |
| 可能产生费用的云端 API | DeepSeek `/chat/completions` | 仅当 `.env` 配置 `DEEPSEEK_API_KEY` 且 `LLM_MODE` 非 mock 时调用 |
| 可选付费服务 | 无 | 项目未默认依赖任何付费服务 |

## 五、Mock 模式

- 触发：未配置 `DEEPSEEK_API_KEY`，或显式 `LLM_MODE=mock`（`config.py::Settings.llm_mode` 中 `auto` 会在无 Key 时自动降级 mock）。
- 真实部分：文档解析、清洗、分块、Embedding、向量持久化、混合检索、重排、来源引用、LangGraph 工作流、工具执行、SQLite 读写、评估指标计算，以及模型指纹校验。
- 降级部分：答案生成改为从真实检索片段中抽取原文；意图识别与任务规划改为规则决策器。
- 三态标注：`pipeline.py::generate` 返回 `deepseek` / `mock` / `mock-fallback`（真实 API 失败后的抽取式并加「大模型调用失败」标注），`llm_mode` 如实写入响应。
- 标注：Mock 答案首行、前端顶部横幅与侧边栏均显示「模拟运行」，明确说明不是大模型回答。
- 目的：零成本、零下载即可演示完整业务闭环，并验证工具调用确实发生。

## 六、为什么不用 DeepSeek 做 Embedding

DeepSeek 公开接口以对话补全为主，未提供稳定的通用 Embedding 端点；因此 Embedding 全部本地化，既避免额外 API 费用，也让检索链路可离线复现。

## 七、为什么主链路不用原生 Function Calling

指令同时要求「支持 Function Calling」与「工具调用与模型逻辑解耦」。本项目主链路采用 LangGraph 节点 + 结构化 JSON 决策 + 工具注册表，保证：

1. Mock 模式下仍能真实演示意图识别 → 工具选择 → 工具执行 → 结果整合；
2. 新增工具只需注册 `ToolSpec`，不改动模型提示词；
3. 决策依据（意图、槽位、参数摘要）全部可审计。

DeepSeek 原生 `tools` 能力保留在 `LLMClient.chat_with_tools()` 作为兼容接口，供后续扩展或对照实验使用。

## 八、环境兼容性

实测环境：Windows / Python 3.13.14。默认依赖全部安装成功（含 langgraph 1.2.22、fastapi 0.163.1、streamlit 1.67.0、pydantic 2.14.3）。`torch`、`sentence-transformers`、`chromadb` 因体积与 Python 3.13 wheel 兼容性被隔离为可选依赖；若未安装或加载失败，`local` 档会降级为词面哈希向量、SQLite 向量表照常工作，并在 `/api/health` 与前端侧边栏如实显示「实际档位 / 是否语义向量 / 降级原因」。本次环境中 `sentence-transformers` / `torch` / `chromadb` 安装超过 29 分钟无进展，已主动停止，因此 **BGE 语义向量、CrossEncoder 模型重排、Chroma 向量库均未运行 / 未验证**；`docs/evaluation_report.md` 的「未运行说明」为最终准绳，报告未生成任何模型指标。
