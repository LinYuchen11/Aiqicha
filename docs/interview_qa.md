# 面试问答索引（结合本项目真实实现）

> 每个回答都能在仓库中找到对应代码，不使用「大概 / 可能 / 理论上」的模糊表述。

## 1. 为什么企业需要这个系统？

企业知识散落在制度、行政、人事、IT 手册、流程文件与 FAQ 中，员工靠翻文档或问同事获取信息，成本高、口径不一致。系统把文档统一入库，用 RAG 给出**带出处的答案**，再用 Agent 把「查完还要自己提单」的动作串起来。业务价值是降低重复咨询、缩短知识获取路径、让制度口径可追溯。对应 `README.md` §2–3。

## 2. 为什么使用 RAG，而不是直接调用大模型？

通用大模型不知道企业内部制度，直接问会编造条款、金额与审批层级；把制度全部塞进 Prompt 既不经济也不可追溯。RAG 把「找依据」和「写答案」分开：检索阶段给出真实文本块与分数，生成阶段只依据这些资料作答并标注【来源 N】。本项目在系统提示与 Mock 抽取式答案中都强制「资料不足时明确告知」，见 `rag/prompt.py`、`llm/mock.py`。

## 3. RAG 的完整工作原理是什么？

两条链路。入库：上传校验 → SHA256 去重（仅 default 集合）→ `insert_document`（状态「解析中」）→ 按类型解析（`parsers.py` 内部调 `cleaner.clean_text` 清洗，保留章节/PDF 页码）→ 分块 → `replace_chunks` 写文本块（状态「向量化中」）→ Embedding + 向量 upsert + `model_guard.mark_written` 登记指纹 → 状态「已完成」。问答：Agent 侧 `resolve_query` 先做上下文改写得到 `resolved_query` → `retriever.search` 首行 `normalize_query` 归一 → 检索前 `assert_compatible` 校验模型指纹 → 原始余弦向量检索 + BM25 关键词检索 → min-max 归一化后加权混合 → **取 Top-K 之前**做无答案三判据 → Top-K → 可选重排 → 构建含注入防护的 Prompt → 模型/抽取式生成 → 真实来源引用。见 `docs/rag_workflow.md`、`services/document_service.py`、`rag/retriever.py`、`rag/pipeline.py`。

## 4. 为什么使用 LangGraph？

Agent 需要显式的状态与条件分支，而不是一串 if-else 或单个大模型调用。LangGraph 的 `StateGraph` 让「意图 → 规划 → 分支 → 工具 → 整合」成为可检查、可扩展的图；简单查询跳过不必要节点，工单创建可挂起等待用户确认再恢复，多工具任务还能通过受控回边连续执行。状态在节点间流转，会话级状态持久化在 SQLite。见 `agent/graph.py`、`agent/state.py`。

## 5. Agent 与普通 RAG 有什么区别？

普通 RAG 只有「检索 → 生成」一条路径。本项目 Agent 先做意图识别（`agent/intent.py::INTENT_LABELS` 共 9 类，含 `multi_tool` 与 `ticket_confirm`）和任务规划，再按 `planner.py::ROUTES` 产出 route 键决定走检索、工具、追问还是待确认分支；能组合多个工具结果、通过受控回边连续执行工具，能执行真实 Python 函数写数据库，能在缺少信息时主动追问，并把每一步写入可审计的 trace。见 `docs/agent_workflow.md`。

## 6. Agent 如何判断调用哪个工具？

主链路不依赖模型内置 function calling：意图识别产出 intent 与 slots，任务规划产出 route（`retrieve / it_tool / tool / collect / confirm / direct`），`tool_select_node` 按意图从**工具注册表**匹配工具并构造参数，`tool_execute_node` 通过 `invoke()` 统一执行。工具与模型解耦，新增工具只注册一个 `ToolSpec`。`route_after_tool` 还能依据上一步工具结果把流程回边到 `tool_select` 继续执行第二个工具。DeepSeek 原生 tools 保留在 `LLMClient.chat_with_tools()` 作兼容接口。见 `tools/registry.py`、`agent/nodes.py`、`agent/planner.py`。

## 7. 如何处理多轮对话？

历史消息按 `session_id` 持久化在 SQLite，每次取最近 8 条作上下文；`resolve_query` 对短追问拼接上一轮用户问题，实现指代与补充条件理解；待确认工单存在 `conversations.pending_ticket`，刷新页面后通过 `/api/sessions/{id}/pending` 恢复；工单信息不全时还会写入 `pending_intent=ticket_create`，下一轮只回「联系方式 13800000000」这样的补充信息时 `intent_node` 会恢复挂起意图并合并上一轮问题，不会被判成 `unknown`。重置只清空当前会话。见 `database/conversation_repo.py`、`agent/intent.py`、`agent/nodes.py::intent_node`。

## 8. 如何避免模型产生幻觉？

四层：①系统提示强制「只依据检索资料」「资料不足直接说明」「推断需标注（推断）」；②检索层在取 Top-K 之前用**三判据同时满足**判定资料不足——命中二元字组数 < 4、最大覆盖率 < 0.30、最高原始余弦 < 0.5（`rag/retriever.py` 常量与 `search`），命中为空时直接返回「资料不足」而不是拼接无关片段；③来源引用全部取自真实向量记录；④Mock 模式只做原文抽取，不做任何补全，真实 API 调用失败时降级为 `mock-fallback` 并加「大模型调用失败」标注。另加文档注入防护：`sanitize_snippet` 中和角色标记与「忽略以上指令」类文本。见 `rag/prompt.py`、`rag/retriever.py`、`rag/pipeline.py`。

## 9. 如何判断检索结果是否准确？

建立统一测试问题集，每题人工审核标注「相关块标识（`文档::章节`）」作为显式相关文本范围：`_evidence_specs` 按文档配对解析，`_hit_matches_evidence` 要求文档名相同且章节包含，分母固定为标注范围总数，因此不同分块方案之间 Recall@K 可比。程序在向量库中真实检索并计算 Recall@K（命中范围数/标注范围总数，按题平均）、MRR（首个相关结果排名倒数，按题平均）、命中率、真实响应时间、无答案正确率，以及新增的「答案-上下文一致性」（标准答案二元字组被 Top-K 上下文覆盖的词面支撑率，不调用大模型）。答案正确性与来源引用准确性属于人工判读，界面提供录入但默认「待人工评估」，绝不代填。见 `services/evaluation_service.py`、`data/evaluation/test_questions.json`、`docs/evaluation_report.md`。

## 10. 如何优化 RAG 的检索效果？

本项目做了**五组**可复现实验：分块策略（固定长度 vs 句末优先、不同 Chunk Size/Overlap）、Top-K（3/5/10）、检索方式（纯向量/关键词/混合）、重排序（原始 / 规则式 / CrossEncoder 模型）、Embedding 模型对照（hash vs 本地 BGE）。实验用独立 `eval_*` collection，不影响在线问答；报告如实展示未提升的方案，模型不可用的方案标注「未运行」而非填数值。见 `scripts/run_evaluation.py`、`services/evaluation_service.py`、`docs/evaluation_report.md`。本次环境 `sentence-transformers` / `torch` 安装超过 29 分钟无进展已主动停止，BGE 与 CrossEncoder 方案均标注「未运行」，报告中未生成任何模型指标。

## 11. 为什么选择这些技术？

FastAPI + Streamlit 让中文界面与接口快速可运行；LangGraph 提供可解释的有状态编排；默认 `hash` 档是**词面哈希向量（非语义 Embedding）**配合 SQLite 向量表，实现零下载、零费用、可持久化，保证任何人 clone 后「只装默认依赖」也能跑通完整链路；`local`（BAAI/bge-small-zh-v1.5）、Chroma、bge-reranker 作为正式演示推荐 / 可选增强；DeepSeek 通过环境变量接入，缺失时自动降级 Mock。不同档位的向量由 `embedding_meta` 指纹隔离、切换时强制重建。免费与付费边界见 `docs/tech_stack.md`。

## 12. 项目有哪些不足，下一步如何优化？

不足：默认哈希向量非语义模型；`rule` 重排为确定性打分而非模型；仅 6 份模拟文档、有限测试题；Mock 答案无推理能力；无登录与文档级权限；工单为模拟状态机；无 OCR 与 ANN 索引；本次环境未配置 `.env` / DeepSeek Key，真实 API 未验证；可选依赖 `sentence-transformers` / `torch` 安装超过 29 分钟无进展已主动停止，BGE 与 CrossEncoder 实验按报告标注「未运行」。第二轮已补齐能力骨架：模型指纹校验与向量重建、真实 CrossEncoder 批量重排、第五组 Embedding 对照实验、答案-上下文一致性指标、Agent 受控回边与专项评估。下一步是**在可下载模型的环境中安装可选依赖后真实复跑模型方案**、扩展标注题集、接入 SSO 与权限、对接真实 ITSM、增量索引与 ANN。完整清单见 `README.md` §17–18。

## 13. 为什么 `hash` 向量不能叫语义 Embedding？两档如何定位？

`rag/embeddings.py::HashEmbedder.encode_one` 的做法是：`tokenize_for_search` 把文本切成单字、相邻二元字组与英文词，每个 token 用 blake2b 取 4 字节哈希后按 `% 256` 分桶累加，再做 `log1p` 与 L2 归一化。整个过程是**字符 n-gram 的词面统计**，没有训练、没有语义空间，「打印机」和「复印设备」不会因为语义相近而靠近，只能匹配字面重合。因此 `HashEmbedder.name` 明确写「内置词面哈希向量（离线备用，非语义 Embedding）」，`embedding_info()` 返回「是否语义向量 = False」并给出中文说明。

`local` 档（`LocalEmbedder`）才用 `SentenceTransformer.encode(normalize_embeddings=True)` 产出真正的语义向量，`RECOMMENDED_MODE = "local"`、`config.py::Settings.public_dict()` 都把 `local`（BAAI/bge-small-zh-v1.5）标为「正式演示推荐档位」。但 `config.py` 与 `.env.example` 的 `EMBEDDING_MODE` 默认仍是 `hash`，理由写在注释里：保证「只装默认依赖」也能跑通完整链路。`frontend/app.py` 侧边栏在非语义档时额外显示提示；切换用 `scripts/switch_embedding.py`。见 `rag/embeddings.py`、`core/config.py`、`frontend/app.py`。

## 14. 如何防止不同 Embedding 模型的向量混用？

`rag/embeddings.py::embedding_fingerprint` 生成 `model_key`（`hash:256` 或 `local:模型名:维度`）；`database/schema.py` 的 `embedding_meta(collection, model_key, model_name, dim, effective_mode, updated_at)` 按集合记录「这批向量由哪个模型生成」。三道关卡：

1. **写入时**：`rag/model_guard.py::mark_written` 校验本批向量维度都等于当前模型维度，不一致直接抛 `VectorError`；通过后登记指纹。
2. **检索前**：`retriever.py::search` 首段调用 `assert_compatible`。集合非空但来源标记缺失、或 `model_key` 与当前模型不一致，抛中文 `VectorError` 并提示执行 `python scripts/rebuild_vectors.py`；向量计算（余弦矩阵）异常也不再静默降级为关键词检索，而是同样抛错，避免使用者误以为语义检索仍生效。
3. **切换模型后**：`services/document_service.py::reconcile_vector_model` 比对指纹，不一致就 `delete_collection` + `clear_meta`，再按原始文件逐文档 `reprocess_document` 重建；`scripts/switch_embedding.py`、`scripts/rebuild_vectors.py` 是入口，`compatibility_status` 供 `/api/health` 只读展示。

见 `rag/model_guard.py`、`rag/retriever.py`、`services/document_service.py`、`database/schema.py`。

## 15. 评估标准答案为什么从启发式改成显式标注、且分母固定？新增指标怎么算？

`services/evaluation_service.py::_evidence_specs` 的注释写清了旧实现的问题：把「相关文档 + 相关章节关键词」做**全局 OR** 匹配，跨文档题的相关集被放大，而且分母随分块方案变化，导致 Recall@K 在不同方案间不可比。现在 `data/evaluation/test_questions.json` 每题人工审核标注「相关块标识（`文档::章节`）」作为显式相关文本范围，`_evidence_specs` 按 `::` 拆成「文档 / 章节」配对，`_hit_matches_evidence` 要求 `doc_name` 相同且章节包含才算命中；**分母 = 该题标注范围总数，固定不变**，因此跨分块方案可比。`_evaluate_question` 据此算 recall_at_k、reciprocal_rank 与 hit，`_aggregate` 汇总。

新增指标「答案-上下文一致性」由 `_context_support` 计算：取标准答案 `tokenize_for_search` 后长度 ≥ 2 的二元字组集合，计算它们出现在 Top-K 各 `hit.text` 二元字组并集中的比例。`METRIC_NOTES` 明确它是**词面支撑率代理指标**，确定性、不调用大模型、不是语义忠实度，抽取式答案天然偏高，仅用于同测试集的方案间对照。无答案正确率的口径也与检索器三判据一致（命中二元字组数 < 4 且最大覆盖率 < 0.30 且最高原始余弦 < 0.5）。报告由 `scripts/run_evaluation.py` 生成，见 `docs/evaluation_report.md`。

## 16. CrossEncoder 与规则式重排有什么区别？如何避免把降级或未验证结果当成模型结果？

`rag/rerank.py::apply_rerank` 有 `none / rule / local` 三档：

- `rule`：`_rule_score = 0.55×原综合分 + 0.35×关键词覆盖率 + 章节加成 − 长度惩罚`，是确定性打分、不是模型；返回的 `method` 如实写「规则式重排序（非模型）」。
- `local`：`_get_cross_encoder()` 加载 `sentence_transformers.CrossEncoder(BAAI/bge-reranker-base)`，一次 `predict([(query, hit.text)...], batch_size=16)` 批量前向打分，`method` 写「CrossEncoder 模型重排序」。

避免混淆的机制：`cross_encoder_status()` 在 `importlib.util.find_spec("sentence_transformers") is None` 时直接判「不可用」，不触发下载；模型加载失败时 `apply_rerank` 把 `method` 改写成「规则式重排序（CrossEncoder 不可用降级，非模型）」；`evaluation_service.py::_build_schemes("rerank")` 只有 `status["可用"]` 才追加「CrossEncoder 模型重排序」方案，否则写进 `_SKIP_NOTES`；`run_embedding_comparison` 在 BGE 降级时 `continue`，只写「未运行方案说明」，不生成任何数值。`docs/evaluation_report.md` 的「未运行说明」是最终准绳。

同一原则用在真实验证上：`scripts/verify_deepseek.py::_real_api_ready` 检查 `deepseek_api_key` 与 `settings.is_mock`，不满足就 `_print_unverified` 输出「真实 DeepSeek API 未验证」、8 项检查全记「未验证」，且**不调用** `_write_report`，`docs/deepseek_verification.md` 保持未验证模板。因此如实表述是「本次环境未配置 Key，真实 API 未验证；系统其余链路在 Mock 模式下可复现」，不能说「已通过验证」。见 `rag/rerank.py`、`services/evaluation_service.py`、`scripts/verify_deepseek.py`。

## 17. LangGraph 回边如何依据工具结果决策？`needs_clarification` 如何改变路由？

`agent/graph.py` 注册了 `add_conditional_edges("tool_execute", route_after_tool, {"retrieve": ..., "integrate": ..., "next_tool": "tool_select"})`，其中 `next_tool` 就是回到 `tool_select` 的**受控回边**。`planner.py::route_after_tool` 取 `tool_results[-1]` 的 `status` 与 `result`：`it_consult` 服务目录查询成功才 `retrieve` 继续检索知识库、失败直接 `integrate`；`multi_tool` 在第一步 `found` 且 `items` 非空、且 `plan_index < 2` 时返回 `next_tool` 继续第二个工具；其余 `integrate`。`nodes.py::tool_execute_node` 每次执行完把 `plan_index + 1`，`tool_select_node` 按 `plan_index` 0 → `it_service_query`、1 → `ticket_query`；整合前 `tool_guard.sanitize_tool_results` 还会校验结果来源，丢弃不合法条目。

`needs_clarification`：`planner.py::plan_steps` 在真实模型模式下对复杂意图调用 `build_plan_prompt`，模型返回 `needs_clarification = true` 与 `clarifying_question` 时写入状态；`route_by_intent` **优先**返回 `collect`，把路径改到 `collect_info`；`collect_info_node` 直接输出追问、不误生成工单草稿。另外 `intent.py::_rule_decision` 把 `multi_tool`（「先查…再查…」）放在最前面优先判定，避免被 `ticket_query` 拦截。见 `agent/graph.py`、`agent/planner.py`、`agent/nodes.py`、`agent/intent.py`。

## 18. 如何区分模型决策与规则回退？Agent 专项评估四项指标怎么算？

`agent/state.py` 新增 `decision_source / plan_source / fallback` 三个字段：`intent.py::classify` 在模型意图识别失败时回退规则决策器并把 `source` 设为「规则决策器（模型失败回退）」、`fallback = True`；`planner.py::plan_steps` 在模型规划失败时回退「规则规划器」并置 `fallback = True`；`nodes.py` 把来源写入状态，`chat_service.py::_to_response` 透传到 `ChatResponse`；`agent_evaluation_service.py::evaluate_question` 用 `getattr` 读取写入评估明细（不假设字段一定存在）。所以「这次是模型决策还是规则回退」是可观测、可复核的，不是靠猜。

Agent 专项评估四项指标（`services/agent_evaluation_service.py::METRIC_DEFINITIONS` 与 `aggregate_metrics`）：

1. **意图识别准确率** = `expected_intent` 与 `ChatResponse.intent` 相等的题数 ÷ 总题数；
2. **工具选择准确率** = `set(expected_tools) == set(实际工具名)` 的题数 ÷ `expected_tools` 非空的题数；空期望工具的题不计入分母（明细标「不适用」），但集合比较仍按空集相等规则写入明细；
3. **工具执行成功率** = 所有 `tool_results` 中 `status == "成功"` 的调用数 ÷ 总调用数；整次运行无任何工具调用时记「无样本」（值为 `None`），绝不填 1.0；
4. **任务完成率** = 按每题 `completion_rule` 由 `judge_completion` 结合 `RULE_DEFINITIONS` 确定性判定的完成题数 ÷ 总题数，不接受人工填写的完成标记。

题集 `data/evaluation/agent_questions.json` 是 16 题人工标注，期望值以「Mock 规则决策器」下系统真实可复现的行为为准；`run_agent_evaluation()` 逐题真实调用 `chat_service.chat()`，并把 `db_path / upload_dir / vector_dir` 重定向到临时目录、结束时恢复，不污染真实运行库；`scripts/run_agent_evaluation.py` 生成 `docs/agent_evaluation_report.md`，报告明确标注评估对象为 Mock 规则决策器、「真实 DeepSeek 模式下未验证」。
