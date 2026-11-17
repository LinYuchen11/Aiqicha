"""DeepSeek 模型封装（OpenAI 兼容协议）。

支持：环境变量密钥、可配 Base URL / 模型名、流式输出、JSON 结构化输出、
Function Calling 兼容接口。密钥只在请求头中使用，不写入日志、不落到响应里。
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from backend.core.config import settings
from backend.core.errors import LLMError
from backend.core.log_utils import get_logger

logger = get_logger(__name__)


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


class LLMClient:
    def __init__(self) -> None:
        self.mode = settings.llm_mode
        self.model = settings.deepseek_model
        self.base_url = settings.deepseek_base_url
        self.api_key = settings.deepseek_api_key
        self.timeout = settings.llm_timeout
        self.max_tokens = settings.llm_max_tokens

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    def _payload(self, system: str, user: str, json_mode: bool, temperature: float, max_tokens: int | None) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _raise_for_status(self, status: int, body: str) -> None:
        if status == 401:
            raise LLMError("DeepSeek API Key 无效或已过期", "请检查 .env 中的 DEEPSEEK_API_KEY")
        if status == 429:
            raise LLMError("大模型调用频率超限", "请稍后重试或检查账户额度")
        if status >= 500:
            raise LLMError("大模型服务暂时不可用", f"HTTP {status}")
        raise LLMError("大模型请求被拒绝", f"HTTP {status}：{body[:200]}")

    def complete(
        self,
        system: str,
        user: str,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """非流式生成。Mock 模式下不会发起任何网络请求。"""
        if self.is_mock:
            return ""
        payload = self._payload(system, user, json_mode, temperature, max_tokens)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0)) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError("大模型请求超时", "请稍后重试，或增大 .env 中的 LLM_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise LLMError("无法连接大模型服务", str(exc)) from exc
        if response.status_code != 200:
            self._raise_for_status(response.status_code, response.text)
        try:
            return response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise LLMError("大模型返回格式异常", "响应中缺少 choices[0].message.content") from exc

    def complete_json(self, system: str, user: str, temperature: float = 0.0) -> dict:
        """结构化输出；解析失败时抛出明确异常，由调用方走规则兜底。"""
        raw = self.complete(system, user, json_mode=True, temperature=temperature, max_tokens=500)
        try:
            parsed = json.loads(_strip_fence(raw))
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError) as exc:
            raise LLMError("结构化输出解析失败", "模型未返回合法 JSON") from exc

    def stream(self, system: str, user: str, temperature: float = 0.3) -> Iterator[str]:
        """流式输出，逐段产出文本。"""
        if self.is_mock:
            yield "【模拟运行】当前未调用真实大模型，流式输出不可用。"
            return
        payload = self._payload(system, user, False, temperature, None)
        payload["stream"] = True
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0)) as client:
                with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        self._raise_for_status(response.status_code, "")
                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                        except (ValueError, KeyError, IndexError, TypeError):
                            continue
                        if delta:
                            yield delta
        except httpx.TimeoutException as exc:
            raise LLMError("大模型流式请求超时", "请稍后重试") from exc
        except httpx.RequestError as exc:
            raise LLMError("无法连接大模型服务", str(exc)) from exc

    def chat_with_tools(self, system: str, user: str, tools: list[dict]) -> dict:
        """Function Calling 兼容接口。

        主链路使用 LangGraph 结构化决策以保证工具与模型解耦；本方法保留
        DeepSeek 原生 tools 能力，供后续扩展或对照实验使用。
        """
        if self.is_mock:
            return {"tool_calls": [], "content": "【模拟运行】原生工具调用能力不可用。"}
        payload = self._payload(system, user, False, 0.0, None)
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0)) as client:
                response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise LLMError("无法连接大模型服务", str(exc)) from exc
        if response.status_code != 200:
            self._raise_for_status(response.status_code, response.text)
        try:
            message = response.json()["choices"][0]["message"]
            return {"tool_calls": message.get("tool_calls") or [], "content": message.get("content") or ""}
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError("工具调用返回格式异常", str(exc)) from exc

    def health(self) -> dict:
        return {
            "模式": self.mode,
            "模型": self.model if not self.is_mock else "本地抽取式模拟器",
            "接口地址": self.base_url if not self.is_mock else "未调用外部接口",
            "密钥已配置": bool(self.api_key),
            "支持流式输出": True,
            "支持结构化输出": True,
            "支持原生工具调用": True,
        }
