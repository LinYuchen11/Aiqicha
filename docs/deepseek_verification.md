# 真实 DeepSeek API 验证报告

> **当前状态：未验证。**
>
> 本报告为「未验证」状态模板。项目当前未在项目根 `.env` 中配置 `DEEPSEEK_API_KEY`，
> 因此尚未对真实 DeepSeek API 发起任何请求。为保持诚实，本报告**不记录任何 Mock 模拟
> 结果，也不填写任何虚构的耗时或数值**。
>
> 只有执行 `python scripts/verify_deepseek.py` 且脚本确实对真实 DeepSeek API 发起请求、
> 跑完全部 8 项检查后，脚本才会用真实结果覆盖本文件。

## 当前状态

| 项目 | 内容 |
| --- | --- |
| 总体结论 | **真实 DeepSeek API 未验证** |
| 运行模式 | Mock（本地抽取式模拟器，非真实大模型） |
| 是否已配置 `DEEPSEEK_API_KEY` | 否 |
| 是否已对真实接口发起请求 | 否 |
| 数据来源 | 无（未运行真实验证，不写入模拟结果） |

## 8 个检查项（当前均为「未验证」）

| 编号 | 检查项 | 当前状态 | 耗时 | 说明 |
| --- | --- | --- | --- | --- |
| ① | 基础问答 | 未验证 | — | 验证 `LLMClient.complete()` 能否调用真实模型返回非空回答 |
| ② | RAG 问答 | 未验证 | — | 验证 `RAGPipeline.generate()` 能否基于检索片段让真实模型生成答案 |
| ③ | 结构化 JSON 输出 | 未验证 | — | 验证 `LLMClient.complete_json()` 能否让真实模型输出并解析 JSON |
| ④ | 意图识别 | 未验证 | — | 验证 `classify()` 在真实模式下走 DeepSeek 结构化输出 |
| ⑤ | 任务规划 | 未验证 | — | 验证 `plan_steps()` 在真实模式下走 DeepSeek 结构化规划 |
| ⑥ | 多轮对话 | 未验证 | — | 验证 `chat_service.chat()` 连续多轮对话保持会话并返回回答 |
| ⑦ | API 超时 | 未验证 | — | 用极小 timeout 真发请求，验证捕获「大模型请求超时」中文错误 |
| ⑧ | API 错误及降级 | 未验证 | — | 用无效 Key 真发请求捕获中文错误；验证失败时返回抽取式、带标注且不被伪装成模型答案 |

> 说明：表中「耗时」一律记为 `—`，表示未执行真实验证，不填任何估算或虚构数值。

## 需要你做什么

1. 在项目根目录把 `.env.example` 复制为 `.env`：

   ```bash
   cp .env.example .env
   # Windows CMD / PowerShell：
   # copy .env.example .env
   ```

2. 用文本编辑器打开 `.env`，在 `DEEPSEEK_API_KEY=` 后填写你自己的真实密钥
   （**密钥只放在 `.env` 中，不要写进任何代码或提交到仓库**）。
   其余可选项按需调整，例如 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`LLM_TIMEOUT`。
   `LLM_MODE` 请保持 `auto` 或设为 `deepseek`，不要设为 `mock`。

3. 运行验证脚本：

   ```bash
   python scripts/verify_deepseek.py
   ```

4. 脚本会真正向 DeepSeek API 发起请求，逐项记录「通过 / 失败 / 未验证」、中文说明与
   真实耗时；**只有这次真实运行跑完后**，脚本才会把结果写入本文件。

5. 若仍提示「真实 DeepSeek API 未验证」，请确认 `.env` 位于项目根目录、密钥非空，
   且 `LLM_MODE` 未强制为 `mock`。

## 约束声明

- 全部文字使用中文；不写死任何密钥；不硬编码伪装成功。
- 未配置 Key 时，脚本正常退出（非崩溃）并打印中文提示，报告保持「未验证」。
- 超时项通过「极小 timeout + 真实 HTTP 请求」触发，绝不使用 `sleep` 假装超时。
- 错误项使用明显无效的 Key 真发请求并捕获中文错误；降级项验证返回的是抽取式内容、
  带「【大模型调用失败】」标注，并明确声明不是模型生成的答案。
