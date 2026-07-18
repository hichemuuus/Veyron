"""Remote LLM provider — OpenAI-compatible API.

Supports any OpenAI-compatible endpoint (OpenAI, Together AI, Groq, etc.).
Used as a graceful fallback when the local Ollama provider is unavailable.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from veyron.llm.base import (
    GenerateChunk,
    GenerateOptions,
    LLMProvider,
    LLMRetryableError,
    LLMUnavailableError,
    Message,
)

logger = logging.getLogger(__name__)

_RETRYABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
    httpx.StreamError,
    LLMRetryableError,
)


class RemoteProvider(LLMProvider):
    """OpenAI-compatible remote LLM provider.

    Connects to any OpenAI-compatible chat completions API. Supports
    streaming, tool calls, and embeddings.
    """

    name = "remote"

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        embedding_model: str = "text-embedding-3-small",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.timeout = timeout
        self._chat_url = f"{self.base_url}/chat/completions"
        self._embed_url = f"{self.base_url}/embeddings"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def is_available(self) -> bool:
        if not self.base_url or not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except (httpx.HTTPError, OSError) as e:
            logger.debug("remote provider not available: %s", e)
            return False

    async def generate_stream(
        self, messages: list[Message], opts: GenerateOptions
    ) -> AsyncIterator[GenerateChunk]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._serialize_message(m) for m in messages],
            "stream": True,
            "temperature": opts.temperature,
            "max_tokens": opts.max_tokens,
        }
        if opts.stop:
            payload["stop"] = opts.stop
        if opts.allow_tools and opts.tools:
            payload["tools"] = [self._to_openai_tool(t) for t in opts.tools]
            payload["tool_choice"] = "auto"

        retrier = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=8),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )

        async for attempt in retrier:
            with attempt:
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        async with client.stream(
                            "POST",
                            self._chat_url,
                            headers=self._headers(),
                            json=payload,
                        ) as resp:
                            if resp.status_code != 200:
                                body = await resp.aread()
                                if 500 <= resp.status_code < 600:
                                    raise LLMRetryableError(
                                        f"remote /chat/completions returned {resp.status_code}: {body[:500]!r}"
                                    )
                                raise LLMUnavailableError(
                                    f"remote /chat/completions returned {resp.status_code}: {body[:500]!r}"
                                )
                            async for line in resp.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                data_str = line[6:].strip()
                                if not data_str or data_str == "[DONE]":
                                    continue
                                try:
                                    chunk_json = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue

                                choices = chunk_json.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                finish_reason = choices[0].get("finish_reason")

                                content = delta.get("content", "")
                                if content:
                                    yield GenerateChunk(text=content)

                                tool_calls = delta.get("tool_calls")
                                if tool_calls:
                                    for tc in tool_calls:
                                        fn = tc.get("function", {})
                                        args_raw = fn.get("arguments", "{}")
                                        try:
                                            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                                        except json.JSONDecodeError:
                                            args = {"raw": args_raw}
                                        yield GenerateChunk(
                                            tool_call={
                                                "id": tc.get("id", f"call_{abs(hash(args_raw)) % 10**10}"),
                                                "name": fn.get("name", ""),
                                                "arguments": args,
                                            }
                                        )

                                if finish_reason:
                                    fr_map = {
                                        "stop": "stop",
                                        "tool_calls": "tool_use",
                                        "length": "length",
                                    }
                                    yield GenerateChunk(done=True, finish_reason=fr_map.get(finish_reason, "stop"))
                                    return
                except httpx.HTTPError as e:
                    raise LLMRetryableError(f"remote request failed: {e}") from e

                yield GenerateChunk(done=True, finish_reason="stop")

    async def embed(self, text: str) -> list[float]:
        payload = {
            "model": self.embedding_model,
            "input": text,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self._embed_url,
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", [])
                if items:
                    return items[0].get("embedding", [])
                return data.get("embedding", [])
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"remote embed failed: {e}") from e

    def _serialize_message(self, m: Message) -> dict[str, Any]:
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments", {})),
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            out["tool_call_id"] = m.tool_call_id
        if m.role == "tool":
            out["name"] = m.tool_name
        return out

    def _to_openai_tool(self, schema: dict[str, Any]) -> dict[str, Any]:
        params = schema.get("parameters", {}) or {}
        return {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": params,
            },
        }
