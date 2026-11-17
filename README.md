# 通用企业级智能知识管理与任务助手（Enterprise Knowledge Agent）

一个可运行、可交互、可测试、可演示的企业级 **RAG + LangGraph Agent** 应用。项目面向 AI Agent 应用开发岗位作品集，强调真实检索、真实工具执行与真实评估数据，而不是静态页面或硬编码回答。

---

## 1. 项目介绍

系统把企业内部散落的制度、流程、IT 手册等文档统一入库，提供两类能力：

- **企业知识问答**：自然语言提问 → 检索企业知识库 → 生成带真实来源引用的答案。
- **企业任务执行**：自然语言提任务 → Agent 识别意图、规划步骤、选择工具、执行 Python 函数 → 整合结果返回。

预置 6 份明确标注为「模拟企业制度」的文档与 20+ 条测试问题，开箱即可演示完整业务闭环。

## 2. 项目背景

企业内部资料通常分散在规章制度、行政文件、人事制度、IT 服务手册、产品说明、业务规范、培训资料与 FAQ 中。员工遇到问题需要自行翻文档、问同事或找对应部门，知识获取成本高、口径不一致。

## 3. 业务痛点

| 痛点 | 系统对应能力 |
| --- | --- |
| 文档分散、查找慢 | 统一知识库 + 混合检索 |
| 答案没有出处，不敢直接用 | 每个结论附文件名、章节/页码、原始片段、检索分数 |
| 大模型容易编造制度 | 只依据检索资料回答；资料不足时明确告知 |
| 「查完还要自己提单」流程割裂 | Agent 多步骤任务编排 + 工单工具 |
| 重复咨询占用 IT 与 HR 人力 | 自助问答 + 工单自动登记 |
| 效果无法量化 | 独立评估中心，真实计算 Recall@K、MRR、响应时间 |

## 4. 核心功能

1. **知识库管理**：PDF/DOCX/TXT/MD 多文件上传、格式与大小校验、SHA256 去重、空文件与解析失败提示、状态显示、重新处理、级联删除、检索测试、Embedding 信息。
2. **RAG 问答**：Query 归一 → Embedding → 向量/BM25 关键词/加权混合检索 → 可选重排 → Prompt 构建（含注入防护）→ DeepSeek 或 Mock 生成 → 真实来源引用。
3. **Agent**：LangGraph 有状态工作流，9 类意图、任务规划、条件分支、工单确认挂起/恢复、多工具连续执行、多轮上下文与指代识别、可展开执行记录。
4. **工具系统**：IT 服务查询、工单创建、工单状态查询；Pydantic 参数校验、调用日志、结果回传 Agent；工具与模型逻辑解耦。
5. **评估中心**：统一测试问题集、4 组真实实验（分块策略 / Top-K / 检索方式 / 重排序）、Recall@K / MRR / 命中率 / 响应时间、Plotly 对比图、人工评估录入（默认留空）。
6. **运行记录**：文档、文本块、向量、会话、消息、工具日志、工单、实验记录全部持久化；会话隔离。

## 5. 系统架构

五层：前端展示层 → API 服务层 → Agent 工作流层 / RAG 检索层 → LLM 封装层 & 工具执行层 → 数据存储层。

四张与代码一致的图：

- 系统总体架构图：`docs/architecture.md`
- RAG 处理流程图：`docs/rag_workflow.md`
- Agent 工作流图：`docs/agent_workflow.md`
- 用户请求与工具调用时序图：`docs/sequence.md`

## 6. 技术选型及原因

| 组件 | 选型 | 原因 |
| --- | --- | --- |
| 大模型 | DeepSeek API（OpenAI 兼容） | 中文能力强、支持流式与 JSON 结构化输出 |
| 后端 | FastAPI + Uvicorn | 轻量、类型友好、自动生成接口文档 |
| Agent | LangGraph + langchain-core | 显式状态图与条件分支，可解释、可扩展 |
| Embedding | 开箱默认词面哈希向量（离线备用，**非语义 Embedding**）；正式演示推荐本地 BGE `BAAI/bge-small-zh-v1.5` | 默认零下载，保证「只装默认依赖」即可跑通；切换档位由 `backend/rag/model_guard.py` 校验模型指纹并强制重建向量库，禁止不同模型向量混用 |
| 向量库 | 默认 SQLite 向量表；可选 Chroma | 与业务数据同库、重启即持久化 |
| 数据库 | SQLite | 单机零配置 |
| 前端 | Streamlit + Plotly | 中文多页面、图表直观 |
| 校验/测试 | Pydantic v2 / pytest | 参数可靠、场景可回归 |

完整说明与免费/付费边界见 `docs/tech_stack.md`。**默认不依赖任何付费服务。**

## 7. 项目目录

```
Enterprise-Knowledge-Agent/
├── frontend/                # Streamlit 前端
│   ├── app.py               # 中文导航与系统状态
│   ├── api_client.py        # 统一 HTTP 调用
│   ├── components/          # 样式与渲染组件
│   └── pages/               # 5 个中文页面
├── backend/
│   ├── main.py              # FastAPI 入口与中文异常处理
│   ├── api/                 # 6 组路由
│   ├── core/                # 配置、异常、日志脱敏
│   ├── database/            # 表结构、连接、各仓储
│   ├── models/              # Pydantic 契约
│   ├── rag/                 # 解析/清洗/分块/Embedding/向量库/检索/重排/Prompt/管线
│   │   └── model_guard.py   # Embedding 模型指纹校验与防混用（第二轮）
│   ├── llm/                 # DeepSeek 封装与 Mock 模拟器
│   ├── agent/               # LangGraph 状态图、意图、规划、节点
│   │   └── tool_guard.py    # 工具结果运行时来源校验（第二轮）
│   ├── tools/               # 工具注册表与 3 个真实工具
│   └── services/            # 文档、对话、RAG 评估、Agent 专项评估
├── data/
│   ├── sample_docs/         # 6 份模拟企业制度文档
│   ├── evaluation/          # RAG 测试问题集 + Agent 专项标注集
│   ├── vector_db/           # 可选 Chroma 持久化目录
│   └── uploads/             # 上传文件（已忽略提交）
├── tests/{unit,integration}/
├── docs/                    # 架构图、流程图、选型、演示、实验报告、面试问答
│   └── screenshots/         # 5 张真实页面截图
├── scripts/                 # 初始化/导入/评估/切换档位/重建向量/DeepSeek 验证/打包
├── .env.example
├── requirements.txt
├── requirements-optional.txt
├── requirements.lock.txt    # 干净环境实测的精确版本锁定
├── run.py
└── README.md
```

## 8. 环境配置

- 操作系统：Windows / macOS / Linux
- Python：3.11+（实测 3.13.14 可用）
- 内存：默认档位无需 GPU，2 GB 以上即可

```bash
cd Enterprise-Knowledge-Agent
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
```

## 9. 安装依赖

```bash
python -m pip install -r requirements.txt
```

可选（体积大、需下载本地模型，非必需）：

```bash
python -m pip install -r requirements-optional.txt
```

## 10. DeepSeek API 配置

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

编辑 `.env`：

```ini
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
LLM_MODE=auto
```

- 密钥只从环境变量读取，不写入代码、不进入日志、不提交（`.gitignore` 已排除 `.env`）。
- 支持配置 Base URL、模型名、超时与最大 token；封装层支持流式输出、JSON 结构化输出与原生 tools 兼容接口。
- API Key 无效、超时、限流、服务不可用均有中文错误提示；调用失败时 RAG 会降级为抽取式并明确标注，不伪装成模型答案。

## 11. Mock 模式配置

**默认即为 Mock 模式**：只要不填 `DEEPSEEK_API_KEY`，或设置 `LLM_MODE=mock`，即可零成本、零模型下载运行。

真实部分：文档解析、分块、Embedding、向量持久化、混合检索、重排、来源引用、LangGraph 工作流、工具执行、SQLite 读写、评估指标。

降级部分：答案生成改为从真实检索片段抽取原文；意图识别与任务规划改为规则决策器。

界面与答案首行均显著标注「模拟运行」，明确说明不是大模型回答。

## 12. 数据库初始化

```bash
python scripts/init_db.py
```

该脚本创建 `data/knowledge_agent.db` 全部表，并幂等导入 6 份模拟企业制度文档（按内容哈希去重）。后端启动时也会自动执行同样初始化。仅补齐文档可用 `python scripts/ingest_samples.py`。

### 修改知识库文档内容

知识库有两份「内容」：磁盘上的原始文件，以及 SQLite 中已切好并向量化的文本块。**只改磁盘文件不会自动改变检索结果，必须重建向量。**

- **预置模拟制度文档**：`data/sample_docs/*.md`（6 份，UTF-8）。改完后重启后端，或执行 `python scripts/ingest_samples.py`；系统按文件名 + 内容指纹检测变化，用同一个文档编号原地重建文本块与向量，不会残留同名旧记录。
- **自定义文档**：在「知识库管理」页上传 PDF / DOCX / TXT / MD，或选中文档后「删除该文档」「重新处理该文档」；上传副本保存在 `data/uploads/`。
- **调整每次检索送入模型的内容量**：`.env` 的 `DEFAULT_TOP_K`（默认 5，助手页另有 1~15 滑块）、`CHUNK_SIZE`（默认 400）、`CHUNK_OVERLAP`（默认 80）；单条资料进 Prompt 时的截断长度在 `backend/rag/prompt.py::build_context(limit_chars=600)`。

## 13. 启动方法

```bash
python run.py              # 同时启动后端与前端
python run.py backend      # 仅后端
python run.py frontend     # 仅前端
```

也可分别执行：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
python -m streamlit run frontend/app.py --server.port 8501
```

- 前端地址：http://127.0.0.1:8501
- 后端地址：http://127.0.0.1:8000
- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

## 14. 功能演示

见 `docs/demo.md`：9 步 5 分钟演示流程、可验证的真实性证据、异常复现清单、切换真实 API 的方法。

生成真实实验报告：

```bash
python scripts/run_evaluation.py
```

## 15. 测试方法

```bash
python -m pytest tests -q                    # 全部单元测试 + 集成测试
python -m pytest tests/unit -q               # 仅单元测试
python -m pytest tests/integration -q        # 仅集成测试（7 个业务场景）
```

测试使用临时 SQLite 数据库与 Mock 模型，不产生任何 API 费用，不污染运行时数据。集成测试通过 FastAPI TestClient 真实走 HTTP 路由。

覆盖：文档解析、清洗、分块、Embedding、向量检索、混合检索、重排、Prompt 构建与注入防护、意图识别、工具参数校验、工单创建/查询、会话管理；场景 A–G（知识问答、跨文档、IT 故障、工单创建、连续对话、无答案、异常处理）。

## 16. 测试结果（第二轮）

本节数据来自第二轮优化后在 Windows / Python 3.13.14 / Mock 模式下的**真实执行**，未用静态阅读代替运行，也未沿用第一轮的旧数值。

| 检查项 | 命令 | 实测结果 |
| --- | --- | --- |
| 全量自动化测试（主环境） | `python -m pytest -q` | **81 passed**（单测 + 集成场景 A–G + 第二轮模型指纹/Agent/评估/打包回归专项） |
| 干净环境复验 | 新建 `.venv` → 装 `requirements.txt` → `.venv/Scripts/python -m pytest -q` | **81 passed**，与主环境一致；同时生成 75 行精确版本的 `requirements.lock.txt` |
| 交付包解压独立复验 | 把最终 ZIP 解压到全新目录后 `python -m pytest -q` | **81 passed**，验证「拿到 ZIP 就能跑」；此项发现并修复了打包白名单误伤 `backend/models/` 的缺陷，详见 §17 |
| 语法编译 | `python -m compileall -q backend frontend scripts tests` | 全部通过 |
| 页面渲染 | `streamlit.testing.v1.AppTest` 逐页运行 | 主入口 + 5 个页面共 6 个脚本（另含 1 个包初始化文件），**0 异常** |
| FastAPI 接口 | 临时启动 Uvicorn 后真实 HTTP 请求 | `/api/health`、`/api/config`、`/api/documents`、`/api/retrieval/search`、`/api/tools`、`/api/evaluation/overview` 均 200；检索接口返回 3 个真实文本块 |
| 数据库持久化 | 跨进程直读 SQLite | 6 份文档 / 102 文本块 / 3 会话 / 18 消息 / 3 工具日志 / 14 次实验 / 760 条实验记录 / 6 个集合模型指纹 / 人工评估 0 条 |
| 向量库重建 | `python scripts/rebuild_vectors.py` | 首次按模型指纹重建 6 份文档 / 102 条向量；第二次输出「模型指纹一致，无需重建」，幂等 |
| RAG 实验 | `python scripts/run_evaluation.py` | **5 组**实验真实完成，生成 `docs/evaluation_report.md` |
| 关键页面截图 | `scripts/capture_screenshots.py` + Edge 无头浏览器 | 5 张真实渲染 PNG，见 `docs/screenshots/` |
| DeepSeek 验证 | `python scripts/verify_deepseek.py` | 无 Key → 8 项全部标记「未验证」，报告不写入任何伪造结果 |
| Agent 专项评估 | `python scripts/run_agent_evaluation.py` | 16 题真实跑分，生成 `docs/agent_evaluation_report.md` |
| 交付包 | `python scripts/build_release.py` | 123 个文件 / 1.00 MB 的干净 ZIP，排除密钥、数据库、缓存、上传副本、模型缓存；`zipfile.testzip()` 无损坏条目，解压后独立复跑全量测试通过 |

**第二轮真实实验结果摘要**（完整表格见 `docs/evaluation_report.md`）：

- **评估标准答案已修正**：改用人工审核的「文档::章节」显式相关范围、按文档配对、分母固定，Recall@K 不再随分块方案漂移，跨方案真正可比。
- 分块策略：四个方案 Recall@K 均为 0.8333；MRR 句末优先 200/40 最高 0.9583，固定长度 200/40 最低 0.8854。
- Top-K：Top-10 Recall@K 0.9167 最高；MRR 0.9115 与 Top-5 持平。
- 检索方式：混合检索 Recall@K 0.8333 / MRR 0.9115 均为最高（修正标准答案后结论与第一轮不同，如实按新数据记录）。
- 重排序：原始排序与规则式重排三项指标完全相同，**未观察到提升**；CrossEncoder 模型方案因可选依赖未安装**未运行**，报告中明确列出未运行说明。
- 实验五（Embedding 对照）：hash 方案真实运行；BGE 方案因本地模型依赖未安装/未加载**未运行**，未生成任何模型指标。
- 新增「答案-上下文一致性（词面支撑率）」：各方案 0.8082～0.8783；该指标是确定性词面代理，不是语义忠实度。
- 人工评估：状态「待人工评估」，已录入 0 条，系统未代填分数。

**Agent 专项评估（16 题，真实跑分，见 `docs/agent_evaluation_report.md`）**：意图识别准确率 100%（16/16）、工具选择准确率 100%（3/3，分母为有期望工具的题）、工具执行成功率 100%（3/3 次真实调用）、任务完成率 100%（16/16）。该结果**只代表 Mock 规则决策器在其规则覆盖范围内的行为一致性**，报告已明确标注「真实 DeepSeek 模式未验证」，不等于真实模型具备同等能力。

**第二轮修复与增强**：① 新增 `embedding_meta` 模型指纹表与 `model_guard`，切换 Embedding 强制重建、来源不明或模型不一致直接中文报错，杜绝静默降级成关键词检索；② 本地模型镜像 `HF_ENDPOINT` 与降级原因显示；③ 评估标准答案与无答案判据修正（不再使用失效的 0.15 归一化分阈值）；④ CrossEncoder 批量 predict + 未知模式显式降级标注；⑤ 新增答案-上下文一致性指标与第 5 组实验；⑥ LangGraph 增加受控回边实现多工具连续执行，并依据上一步工具结果决定下一步；⑦ 结构化 `decision_source / plan_source / fallback` 贯穿状态、trace 与 API；⑧ 模型规划的 `needs_clarification` 真正驱动追问分支，追问补答可恢复挂起意图；⑨ 工具结果运行时来源校验，剔除伪造条目；⑩ 依赖锁定、白名单打包、`.gitignore` 补全、真实页面截图；⑪ **最终解压复验发现并修复打包缺陷**：`build_release.py` 原先把 `models` 作为「任意层级排除目录」，误伤源码包 `backend/models/`（`schemas.py`），导致初版 ZIP 解压后 `ModuleNotFoundError: No module named 'backend.models'`。已改为「仅顶层排除模型缓存」，新增 `tests/unit/test_release_manifest.py` 4 条回归用例，并重新打包、重新解压复跑全量测试。

**未验证项（如实标注，不含任何推测数据）**：

- 本次环境没有 `.env`、没有 `DEEPSEEK_API_KEY` → **真实 DeepSeek API 8 项在线验证未执行**，Mock 全链路已验证。配置 Key 后运行 `python scripts/verify_deepseek.py` 可一键复验并生成真实报告。
- 可选依赖 `sentence-transformers / torch` 安装在本次环境超过 29 分钟无进展，已主动停止 → **BGE 语义向量与 CrossEncoder 模型重排实验均未运行**，代码与开关完整、加载失败回退已真实验证（实验五运行日志显示自动降级为 hash 并注明原因），但未伪造任何模型实验结果。
- Chroma 向量库、真实 ITSM 状态机、企业 SSO 权限均未验证/未实现。

## 17. 当前不足

1. 开箱默认 hash 档是字符 n-gram 词面哈希，**不是语义 Embedding**，同义/近义表达召回弱于 BGE；正式演示应切换到 `local`。
2. 本次环境未完成 BGE 与 CrossEncoder 模型下载，实验五的模型方案与模型式重排方案**均未运行**，只有 hash / 规则式的真实数据。
3. 评估标准答案粒度是「文档::章节」文本范围，不是逐块人工标注；「答案-上下文一致性」是词面支撑率代理指标，不能替代语义忠实度评估。
4. 模拟企业文档仅 6 份、测试问题 24 条，规模有限，结论不能外推到真实企业知识库。
5. Mock 模式答案是检索片段的原文抽取，不具备真实大模型的归纳与推理能力。
6. 未配置 DeepSeek API Key，真实模型下的意图识别、任务规划、答案生成与降级链路仅做代码级实现，未做在线验证。
7. 工单状态流转、用户登录与组织架构权限均为模拟或未实现；会话隔离仅按 `session_id`。
8. 未内置 OCR，扫描版 PDF 需先转换；未实现增量索引与大规模向量近似检索（ANN）。

## 18. 后续优化方向

1. 在可下载模型的环境中执行 `python scripts/switch_embedding.py local`，重跑 5 组实验，量化 BGE 相对 hash 的检索差异；再启用 CrossEncoder 模型重排方案做三方对照。
2. 把评估标注细化到真实 `chunk_id` 级，并引入人工录入的忠实度评分，完善「自动 + 人工」闭环。
3. 增加查询改写、HyDE、父子块检索与元数据过滤，提升跨文档复杂问题的召回。
4. 配置有效 DeepSeek Key 后运行 `python scripts/verify_deepseek.py`，补齐 8 项真实 API 验证（含超时与错误降级）。
5. 接入企业真实 SSO、组织架构与权限，实现文档级访问控制。
6. 工单系统对接真实 ITSM 状态机，增加分配、处理、关闭与 SLA 计时。
7. 引入增量索引、向量量化与 ANN 索引，支持更大规模知识库。
8. 增加对话导出、反馈标注与基于反馈的检索权重自适应。

---

**数据说明**：`data/sample_docs/` 全部为模拟企业制度文档，明确标注「不代表任何真实企业规定」，不得当作真实公司制度使用。
