# 用户请求与工具调用时序图

> 时序与 `backend/agent/graph.py`、`planner.py`、`nodes.py`、`rag/retriever.py`、`rag/model_guard.py`、`rag/pipeline.py` 一致。

## 一、企业知识问答（场景 A / B / F）

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant S as Streamlit 前端
    participant F as FastAPI /api/chat
    participant G as LangGraph 工作流
    participant R as RAG 检索层
    participant MG as model_guard 模型指纹
    participant V as SQLite 向量表
    participant L as LLMClient / pipeline
    participant D as SQLite 会话表
    U->>S: 输入「年假需要提前几天申请？」
    S->>F: POST /api/chat（含 session_id 与检索参数）
    F->>D: 读取该会话最近 8 条历史
    F->>G: 构造 AgentState 并 invoke
    G->>G: intent（上下文改写 resolved_query）→ planner → route=retrieve
    G->>R: retrieve(resolved_query, top_k, mode, weight)
    R->>MG: assert_compatible 检索前校验模型指纹
    MG->>V: 读取 embedding_meta 与向量数
    alt 来源缺失或模型不一致
        MG-->>R: 抛 VectorError 中文错误（提示重建，绝不静默降级）
    else 一致
        MG-->>R: 校验通过
        R->>V: 载入向量，计算原始余弦 + BM25
        R->>R: 无答案三判据（发生在取 Top-K 之前）
        V-->>R: Top-K 文本块
        R-->>G: RetrievalOutcome（分数、来源、耗时）
        G->>L: integrate → pipeline.generate 构建 Prompt 并生成答案
        alt 配置 DeepSeek Key 且调用成功
            L->>L: 调用 /chat/completions（llm_mode=deepseek）
        else 配置 Key 但调用抛 LLMError
            L->>L: 降级抽取式 + 「大模型调用失败」标注（llm_mode=mock-fallback）
        else Mock 模式
            L->>L: 从真实检索片段抽取原文（llm_mode=mock）
        end
        L-->>G: 答案文本
        G->>G: integrate → final（追加 trace）
        G-->>F: 最终状态
        F->>D: 持久化用户消息与助手消息（含来源/trace）
        F-->>S: ChatResponse
        S-->>U: 答案 + 知识来源 + 执行记录
    end
```

## 二、IT 故障咨询（场景 C）

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant G as LangGraph 工作流
    participant T as 工具注册表
    participant D as SQLite it_services
    participant R as RAG 检索层
    U->>G: 我的电脑连不上公司网络，怎么办？
    G->>G: intent=it_consult → planner → route=it_tool
    G->>T: tool_select 选择 it_service_query
    T->>D: 查询模拟 IT 服务目录
    D-->>T: 服务条目
    T-->>G: 工具执行结果（写入 tool_logs）
    G->>G: route_after_tool 依据 status / result 决定下一步
    alt 服务目录查询成功（route=retrieve）
        G->>R: retrieve 检索故障处理手册
        R-->>G: 带章节与页码的文本块
    else 查询失败（route=integrate）
        G->>G: 直接整合工具错误说明
    end
    G-->>U: 处理建议 + 服务目录结果 + 多来源引用
```

## 三、创建工单与查询状态（场景 D）

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant S as Streamlit 前端
    participant F as FastAPI
    participant G as LangGraph 工作流
    participant T as ticket_create 工具
    participant D as SQLite
    U->>S: 帮我创建工单（含故障描述与联系方式）
    S->>F: POST /api/chat
    F->>G: invoke（action=chat）
    G->>G: collect_info 生成待确认单
    G->>D: 写 conversations.pending_ticket
    G-->>S: pending_confirmation
    S-->>U: 展示字段 + 确认/取消按钮
    U->>S: 点击「确认创建」
    S->>F: POST /api/chat/confirm（confirm=true）
    F->>G: invoke（action=confirm）
    G->>D: 读取 pending_ticket
    G->>T: invoke(ticket_create, confirmed=True)
    T->>D: 生成工单号并 INSERT tickets
    T->>D: 写 tool_logs（时间、参数、结果、耗时）
    T-->>G: 工单编号与状态
    G->>D: 清除 pending_ticket
    G-->>S: 工单编号与处理状态
    U->>S: 查询工单 IT-xxxx-xxxx
    S->>F: POST /api/chat（ticket_query）
    F->>G: invoke → tool_select → tool_execute
    G->>D: SELECT tickets WHERE ticket_no
    D-->>G: 创建时间 / 类型 / 状态 / 处理说明
    G-->>U: 结构化查询结果
```

## 四、第二轮新增时序

### 4.1 多工具连续执行（`multi_tool` + `next_tool` 受控回边）

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant G as LangGraph 工作流
    participant T as 工具注册表
    participant D as SQLite
    U->>G: 先查 VPN 相关 IT 服务，有对应服务再查工单 IT-20261116-0001 的状态
    G->>G: intent=multi_tool（优先判定）→ planner → route=tool
    G->>T: tool_select（plan_index=0）选择 it_service_query
    T->>D: 查询 it_services
    D-->>T: 服务条目（found / items）
    T-->>G: 工具结果 status=成功（写 tool_logs），plan_index 变为 1
    G->>G: route_after_tool：found 且 items 非空且 plan_index 小于 2 → next_tool
    G->>T: 受控回边回到 tool_select（plan_index=1）选择 ticket_query
    T->>D: SELECT tickets WHERE ticket_no
    D-->>T: 工单状态或「未查询到」
    T-->>G: 工具结果（写 tool_logs），plan_index 变为 2
    G->>G: route_after_tool → integrate；tool_guard 校验结果来源
    G-->>U: 两个工具真实执行结果汇总
```

### 4.2 追问补答恢复（`pending_intent`）

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant F as FastAPI
    participant G as LangGraph 工作流
    participant D as SQLite conversations
    U->>F: 帮我创建工单，办公电脑无法连接公司无线网络
    F->>G: invoke（action=chat）
    G->>G: intent=ticket_create → route=collect → collect_info 校验
    G->>D: set_pending 写入 pending_intent=ticket_create
    G-->>U: 追问：还需要补充联系方式等信息
    U->>F: 联系方式 13800000000
    F->>G: invoke（state 带 pending_intent=ticket_create）
    G->>G: intent_node 判定为补充回答，恢复 ticket_create 并合并上一轮问题
    G->>G: collect_info 重新生成待确认工单（仅到待确认，不写工单表）
    G-->>U: 待确认工单字段
```

### 4.3 切换 Embedding 模型与向量库重建

```mermaid
sequenceDiagram
    autonumber
    participant U as 运维
    participant SC as scripts/switch_embedding.py
    participant DS as document_service
    participant MG as model_guard
    participant V as 向量库 / embedding_meta
    U->>SC: python scripts/switch_embedding.py local
    SC->>SC: 写 .env 的 EMBEDDING_MODE，reset_embedder()
    SC->>DS: reconcile_vector_model()
    DS->>MG: current_fingerprint() 与 read_meta()
    MG->>V: 读取 embedding_meta 与向量数
    alt 模型指纹不一致或来源标记缺失
        DS->>V: delete_collection + clear_meta
        DS->>DS: 逐文档 reprocess_document（解析 / 分块 / 向量化）
        DS->>MG: mark_written 登记新模型指纹
    else 指纹一致或集合为空
        DS-->>MG: 无需重建
    end
    SC->>MG: compatibility_status 校验
    MG-->>U: 一致 / 不一致 + 中文提示
```

## 五、说明

- 所有工具调用都经过 `tools/registry.py::invoke`：Pydantic 参数校验 → 真实 Python 函数 → 结果写入 `tool_logs` → 返回给 Agent 整合。
- 工具逻辑与模型解耦：新增工具只需注册一个 `ToolSpec`，Agent 通过工具注册表元数据选择，不依赖模型内置工具绑定。
- 检索前 `model_guard.assert_compatible` 校验 `embedding_meta` 指纹，模型不一致或来源缺失时抛中文 `VectorError`，不静默降级成关键词检索。
- `pipeline.py::generate` 的答案为三态：`deepseek`（真实模型）、`mock`（本地抽取式）、`mock-fallback`（真实 API 失败后的抽取式并带标注），返回值如实写入 `llm_mode`。
- `agent/planner.py::route_after_tool` 依据前一步工具结果（`status`、`result` 的 `found / items`、`plan_index`）决定 `retrieve / next_tool / integrate`；`integrate_node` 整合前由 `agent/tool_guard.py::sanitize_tool_results` 校验工具结果来源，丢弃不合法条目并留痕。
- 时序图中的每个步骤都在代码中有对应函数与持久化记录，不存在「由模型生成一段看似执行成功文字」的伪调用。
- 模型相关方案（BGE 语义向量、CrossEncoder 模型重排）在本次环境中**均未运行**（可选依赖安装超过 29 分钟无进展已主动停止），详见 `docs/evaluation_report.md` 的「未运行说明」；本文件只描述已实现的链路。
