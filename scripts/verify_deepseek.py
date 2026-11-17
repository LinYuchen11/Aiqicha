"""真实 DeepSeek API 验证脚本。

用法：python scripts/verify_deepseek.py

设计原则（务必遵守）：
1. 8 项检查都真正调用项目对应代码，不用 Mock 结果冒充真实 API 通过；
2. 未在项目根 .env 配置 DEEPSEEK_API_KEY（或运行在 Mock 模式）时，
   明确输出「真实 DeepSeek API 未验证」，全部检查记为「未验证」，正常退出；
   此时不改写报告，绝不写入模拟通过结果或虚构数值；
3. 只有确实对真实 DeepSeek API 发起请求并跑完全部检查后，才把真实结果
   写入 docs/deepseek_verification.md；
4. 超时项用「极小 timeout + 真实 HTTP 请求」触发，绝不用 sleep 假装；
   错误项用明显无效的 Key 真发请求并捕获中文错误；
   降级项验证失败时返回的是抽取式且带标注、不伪装成模型答案；
5. 不写死任何密钥，全部用户可见文字使用中文。
"""
from __future__ import annotations

import http.server
import logging
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.config import settings  # noqa: E402

REPORT_PATH = ROOT / "docs" / "deepseek_verification.md"

CHECK_ITEMS = [
    "基础问答",
    "RAG 问答",
    "结构化 JSON 输出",
    "意图识别",
    "任务规划",
    "多轮对话",
    "API 超时",
    "API 错误及降级",
]
CIRCLED = "①②③④⑤⑥⑦⑧"

STATUS_PASS = "通过"
STATUS_FAIL = "失败"
STATUS_UNVERIFIED = "未验证"


@dataclass
class CheckResult:
    index: int
    name: str
    status: str
    detail: str
    elapsed: str


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _real_api_ready() -> tuple[bool, str]:
    """判断是否具备「对真实 DeepSeek API 发起请求」的条件。"""
    if not settings.deepseek_api_key:
        return False, "项目根 .env 中未配置 DEEPSEEK_API_KEY（当前为 Mock 模式）"
    if settings.is_mock:
        return False, "LLM_MODE 被设为 mock（或等效配置），当前不会调用真实 DeepSeek API"
    return True, ""


def _time_call(fn) -> tuple[str, str, str]:
    """真正执行一次检查，记录状态、中文说明与真实耗时。"""
    started = time.perf_counter()
    try:
        status, detail = fn()
    except Exception as exc:  # noqa: BLE001 - 验证脚本需把任意异常转成「失败」而非崩溃
        status = STATUS_FAIL
        detail = f"调用对应代码时抛出异常：{type(exc).__name__}: {exc}"
    elapsed = f"{time.perf_counter() - started:.2f} s"
    return status, detail, elapsed


def _forced_client(base_url: str, api_key: str, timeout: int):
    """构造「强制真实请求」的 LLMClient，用于负向测试（超时 / 错误 / 降级）。

    通过覆写实例属性让 complete() 走真实 httpx 请求分支，且指向受控的本地端点，
    从而确定性地触发失败路径，不依赖外部网络。
    """
    from backend.llm.client import LLMClient

    client = LLMClient()
    client.mode = "deepseek"
    client.base_url = base_url
    client.api_key = api_key
    client.timeout = timeout
    return client


def _sample_outcome():
    """构造包含真实 RetrievedChunk 的检索结果，作为 RAG 生成/降级的真实输入。"""
    from backend.models.schemas import RetrievedChunk
    from backend.rag.retriever import RetrievalOutcome

    hits = [
        RetrievedChunk(
            chunk_id="verify-chunk-1",
            doc_id="verify-doc-1",
            doc_name="员工休假管理制度（验证样例）",
            section="年假",
            page=1,
            text="员工累计工作已满 1 年不满 10 年的，年休假 5 天；"
                 "已满 10 年不满 20 年的，年休假 10 天；已满 20 年的，年休假 15 天。"
                 "国家法定休假日、休息日不计入年休假的假期。",
            snippet="员工累计工作已满 1 年不满 10 年的，年休假 5 天……",
            score=0.91,
            vector_score=0.88,
            keyword_score=0.95,
            rank=1,
        ),
        RetrievedChunk(
            chunk_id="verify-chunk-2",
            doc_id="verify-doc-1",
            doc_name="员工休假管理制度（验证样例）",
            section="请假流程",
            page=2,
            text="员工请年假应至少提前 3 个工作日提交申请，经部门负责人审批后生效；"
                 "未经批准擅自离岗按旷工处理。",
            snippet="员工请年假应至少提前 3 个工作日提交申请……",
            score=0.82,
            vector_score=0.70,
            keyword_score=0.90,
            rank=2,
        ),
    ]
    return RetrievalOutcome(
        query="公司年假有几天、如何申请",
        mode="hybrid",
        top_k=3,
        hybrid_weight=0.6,
        hits=hits,
        total_vectors=len(hits),
    )


# ---------------------------------------------------------------------------
# 受控的本地故障端点（负向测试用，均为真实 socket / 真实 HTTP 请求）
# ---------------------------------------------------------------------------

def _start_blackhole() -> tuple[socket.socket, int]:
    """黑洞端点：接受 TCP 连接但永不返回任何字节，用于真实触发读取超时。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    held: list[socket.socket] = []

    def _hold() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            # 保持连接、不读取也不响应，让客户端在读取响应时真实超时
            held.append(conn)

    threading.Thread(target=_hold, daemon=True).start()
    return srv, port


def _start_401_server():
    class _UnauthorizedHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"invalid api key"}}')

        def log_message(self, *args) -> None:  # 不输出访问日志，避免污染中文结果
            return

    class _Server(http.server.ThreadingHTTPServer):
        daemon_threads = True

    server = _Server(("127.0.0.1", 0), _UnauthorizedHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------------------------------------------------------------------------
# 8 项检查（每项都真正调用项目对应代码）
# ---------------------------------------------------------------------------

def _check_basic() -> tuple[str, str]:
    """① 基础问答：LLMClient.complete() 真实调用。"""
    from backend.llm.client import LLMClient

    answer = LLMClient().complete(
        "你是企业智能知识助手，请用简洁中文回答。",
        "请用一句话说明你能提供什么帮助。",
    )
    if isinstance(answer, str) and answer.strip():
        preview = answer.strip()[:40].replace("\n", " ")
        return STATUS_PASS, f"调用 complete() 获得真实模型非空回答（前 40 字：{preview}）。"
    return STATUS_FAIL, "complete() 返回内容为空，未获得真实模型回答。"


def _check_rag() -> tuple[str, str]:
    """② RAG 问答：RAGPipeline.generate() 基于真实检索片段真实调用模型。"""
    from backend.llm.client import LLMClient
    from backend.rag.pipeline import RAGPipeline

    outcome = _sample_outcome()
    text, mode = RAGPipeline(llm=LLMClient()).generate(
        "公司年假有几天、如何申请", outcome, []
    )
    is_real = (
        isinstance(text, str)
        and text.strip()
        and "【模拟运行】" not in text
        and "【大模型调用失败】" not in text
    )
    if mode == "deepseek" and is_real:
        return STATUS_PASS, (
            "调用 generate() 基于真实检索片段让真实模型生成答案，"
            "llm_mode=deepseek，未出现模拟或降级标注。"
        )
    return STATUS_FAIL, f"RAG 生成未走真实模型：mode={mode}，是否真实答案={is_real}。"


def _check_json() -> tuple[str, str]:
    """③ 结构化 JSON 输出：LLMClient.complete_json() 真实调用。"""
    from backend.llm.client import LLMClient

    data = LLMClient().complete_json(
        "你只输出一个 JSON 对象，不要输出多余文字。",
        '请输出 JSON：{"intent": "knowledge_query", "confidence": 0.9}',
    )
    if isinstance(data, dict) and data:
        return STATUS_PASS, (
            f"调用 complete_json() 让真实模型返回 JSON 并解析为非空字典"
            f"（键：{list(data)[:4]}）。"
        )
    return STATUS_FAIL, "complete_json() 未解析出非空字典。"


def _check_intent() -> tuple[str, str]:
    """④ 意图识别：classify() 在真实模式下走 DeepSeek 结构化输出。"""
    from backend.agent.intent import INTENT_LABELS, classify
    from backend.llm.client import LLMClient

    result = classify("我想查一下公司年假有几天", [], llm=LLMClient())
    source = str(result.get("source", ""))
    intent = str(result.get("intent", ""))
    if source == "DeepSeek 结构化输出" and intent in INTENT_LABELS:
        return STATUS_PASS, (
            f"调用 classify() 在真实模式下走 DeepSeek 结构化输出，"
            f"识别意图「{INTENT_LABELS.get(intent)}」。"
        )
    return STATUS_FAIL, f"意图识别未走真实模型（source={source}，intent={intent}）。"


def _check_plan() -> tuple[str, str]:
    """⑤ 任务规划：plan_steps() 在真实模式下走 DeepSeek 结构化规划。"""
    from backend.agent.planner import plan_steps
    from backend.llm.client import LLMClient

    result = plan_steps(
        "knowledge_query", "请帮我查报销流程并说明需要的材料", {}, llm=LLMClient()
    )
    source = str(result.get("source", ""))
    steps = result.get("steps") or []
    if source == "DeepSeek 结构化规划" and steps:
        return STATUS_PASS, (
            f"调用 plan_steps() 在真实模式下走 DeepSeek 结构化规划，"
            f"产出 {len(steps)} 个步骤。"
        )
    return STATUS_FAIL, f"任务规划未走真实模型（source={source}，步骤数={len(steps)}）。"


def _check_chat() -> tuple[str, str]:
    """⑥ 多轮对话：chat_service.chat() 连续两轮对话。"""
    from backend.models.schemas import ChatRequest
    from backend.services.chat_service import chat

    session_id = "verify-" + uuid.uuid4().hex[:8]
    r1 = chat(ChatRequest(session_id=session_id, message="你好，我想了解公司的休假制度"))
    r2 = chat(ChatRequest(session_id=session_id, message="那年假具体有几天呢？"))
    ok = (
        r1.session_id == r2.session_id
        and isinstance(r1.answer, str) and r1.answer.strip()
        and isinstance(r2.answer, str) and r2.answer.strip()
    )
    if ok:
        return STATUS_PASS, "调用 chat() 连续两轮对话，session_id 保持一致且两轮均返回非空回答。"
    return STATUS_FAIL, "多轮对话未保持同一会话或出现空回答。"


def _check_timeout(blackhole_port: int) -> tuple[str, str]:
    """⑦ API 超时：极小 timeout 向黑洞端点真发请求，验证中文超时错误。"""
    from backend.core.errors import LLMError

    client = _forced_client(
        f"http://127.0.0.1:{blackhole_port}",
        "invalid-verify-" + uuid.uuid4().hex,
        1,
    )
    try:
        # 真正发出 HTTP POST；黑洞端点永不响应，1 秒读取超时后应命中中文超时错误
        client.complete("系统", "用户")
    except LLMError as exc:
        if "超时" in exc.message:
            return STATUS_PASS, (
                f"向黑洞端点真发请求（读取超时 1 秒），"
                f"客户端正确捕获中文错误「{exc.message}」。"
            )
        return STATUS_FAIL, f"请求失败但未命中超时处理，实际错误为「{exc.message}」。"
    return STATUS_FAIL, "向黑洞端点发请求后未抛出超时错误，超时处理未生效。"


def _check_error_and_degradation(port_401: int) -> tuple[str, str]:
    """⑧ API 错误及降级：无效 Key 真发请求捕获中文错误 + 验证抽取式降级。"""
    from backend.core.errors import LLMError
    from backend.rag.pipeline import RAGPipeline

    invalid_key = "invalid-verify-" + uuid.uuid4().hex
    base = f"http://127.0.0.1:{port_401}"

    # (A) 错误项：明显无效的 Key 真发请求，端点返回 401，应捕获中文错误
    err_client = _forced_client(base, invalid_key, 5)
    try:
        err_client.complete("系统", "用户")
        return STATUS_FAIL, "使用明显无效的 Key 发请求后未抛出中文错误，错误映射未生效。"
    except LLMError as exc:
        err_message = exc.message
        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in err_message or "")
        if not err_message or not has_chinese:
            return STATUS_FAIL, f"捕获到的错误不是中文：「{err_message}」。"

    # (B) 降级项：generate() 在模型失败时应返回抽取式且带标注、不伪装成模型答案
    outcome = _sample_outcome()
    pipe = RAGPipeline(llm=_forced_client(base, invalid_key, 5))
    text, mode = pipe.generate("公司年假有几天", outcome, [])
    has_marker = "【大模型调用失败】" in text
    is_extractive = "【模拟运行】" in text or "原文摘录" in text
    has_disclaimer = (
        "不是模型生成的答案" in text
        or "不是大模型回答" in text
        or "不含任何推断" in text
    )
    degraded_ok = (
        has_marker
        and mode == "mock-fallback"
        and is_extractive
        and has_disclaimer
    )
    if degraded_ok:
        return STATUS_PASS, (
            f"错误项：明显无效 Key 真发请求，捕获中文错误「{err_message}」；"
            f"降级项：generate() 失败时返回「{mode}」，含「【大模型调用失败】」标注与"
            "抽取式原文，并明确声明不是模型生成的答案，未伪装成模型答案。"
        )
    return STATUS_FAIL, (
        "降级结果不符合预期："
        f"mode={mode}，含失败标注={has_marker}，抽取式={is_extractive}，"
        f"免责声明={has_disclaimer}。"
    )


# ---------------------------------------------------------------------------
# 运行编排
# ---------------------------------------------------------------------------

def _run_all_checks() -> list[CheckResult]:
    """仅在具备真实 API 条件时调用，逐项真正执行 8 个检查。"""
    logging.getLogger("httpx").setLevel(logging.WARNING)

    blackhole, blackhole_port = _start_blackhole()
    server_401 = _start_401_server()
    port_401 = server_401.server_address[1]

    checks = [
        _check_basic,
        _check_rag,
        _check_json,
        _check_intent,
        _check_plan,
        _check_chat,
        lambda: _check_timeout(blackhole_port),
        lambda: _check_error_and_degradation(port_401),
    ]

    results: list[CheckResult] = []
    for index, fn in enumerate(checks, start=1):
        status, detail, elapsed = _time_call(fn)
        results.append(CheckResult(index, CHECK_ITEMS[index - 1], status, detail, elapsed))

    try:
        server_401.shutdown()
        server_401.server_close()
    except Exception:  # noqa: BLE001 - 清理失败不影响已得到的真实结果
        pass
    try:
        blackhole.close()
    except Exception:  # noqa: BLE001
        pass
    return results


def _print_unverified(reason: str) -> None:
    print("=" * 64)
    print("真实 DeepSeek API 未验证")
    print("=" * 64)
    print(f"原因：{reason}")
    print("本次不会对真实 DeepSeek API 发起任何请求；本地 Mock 模拟结果不会被记为「通过」。")
    print("")
    print("8 项检查当前状态：")
    for i, name in enumerate(CHECK_ITEMS, start=1):
        print(f"  {CIRCLED[i - 1]} {name}  [{STATUS_UNVERIFIED}]  耗时：—  说明：{reason}")
    print("-" * 64)
    print("如何完成真实验证：")
    print("  1. 复制 .env.example 为 .env（Windows: copy .env.example .env）。")
    print("  2. 在 .env 中填写真实的 DEEPSEEK_API_KEY（切勿写死在代码里）。")
    print("  3. 运行：python scripts/verify_deepseek.py")
    print("  4. 脚本会向真实 DeepSeek API 发起请求；运行成功后，")
    print("     真实结果会写入 docs/deepseek_verification.md。")
    print("-" * 64)
    print("docs/deepseek_verification.md 保持「未验证」模板，未写入模拟结果或虚构数值。")
    print("=" * 64)


def _print_results(results: list[CheckResult]) -> None:
    print("=" * 64)
    print("真实 DeepSeek API 验证结果（已对真实接口发起请求）")
    print("=" * 64)
    for r in results:
        print(f"  {CIRCLED[r.index - 1]} {r.name}  [{r.status}]  耗时：{r.elapsed}")
        print(f"      说明：{r.detail}")
    passed = sum(1 for r in results if r.status == STATUS_PASS)
    failed = sum(1 for r in results if r.status == STATUS_FAIL)
    unverified = sum(1 for r in results if r.status == STATUS_UNVERIFIED)
    print("-" * 64)
    print(f"合计：通过 {passed} 项，失败 {failed} 项，未验证 {unverified} 项。")
    print(f"真实结果已写入 {REPORT_PATH.relative_to(ROOT)}。")
    print("=" * 64)


def _write_report(results: list[CheckResult]) -> None:
    """仅在真实运行跑完后，把真实结果写入报告（不含密钥、不虚构数值）。"""
    passed = sum(1 for r in results if r.status == STATUS_PASS)
    failed = sum(1 for r in results if r.status == STATUS_FAIL)
    unverified = sum(1 for r in results if r.status == STATUS_UNVERIFIED)
    if failed:
        overall = "本次真实运行存在失败项，请按上表「中文说明」逐项排查后重试。"
    elif unverified:
        overall = "本次真实运行存在未验证项，请按上表「中文说明」补全条件后重试。"
    else:
        overall = "8 项检查均通过，真实 DeepSeek API 各调用链路验证成功。"

    lines = [
        "# 真实 DeepSeek API 验证报告",
        "",
        "> 本报告由 `python scripts/verify_deepseek.py` 在对真实 DeepSeek API 发起请求后自动生成。",
        f"> 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}。",
        "> 表中耗时为脚本真实测量值；报告不含任何模拟通过结果或虚构数值，也不包含密钥内容。",
        "",
        "## 运行前提",
        "",
        f"- 运行模式：`{settings.llm_mode}`（真实 DeepSeek API）。",
        f"- 接口地址：`{settings.deepseek_base_url}`；模型：`{settings.deepseek_model}`。",
        f"- 密钥已配置：{'是' if settings.deepseek_api_key else '否'}（密钥内容不写入报告）。",
        "",
        "## 8 项检查结果",
        "",
        "| 编号 | 检查项 | 状态 | 耗时 | 中文说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        detail = r.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {CIRCLED[r.index - 1]} | {r.name} | {r.status} | {r.elapsed} | {detail} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        f"- 通过 {passed} 项，失败 {failed} 项，未验证 {unverified} 项。",
        f"- {overall}",
        "",
        "## 复现方式",
        "",
        "```bash",
        "cp .env.example .env   # Windows: copy .env.example .env",
        "# 在 .env 中填写真实 DEEPSEEK_API_KEY",
        "python scripts/verify_deepseek.py",
        "```",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ready, reason = _real_api_ready()
    if not ready:
        _print_unverified(reason)
        return 0
    results = _run_all_checks()
    _print_results(results)
    try:
        _write_report(results)
    except OSError as exc:
        print(f"写入报告失败：{exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
