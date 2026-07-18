"""Ollama LLM provider.

Talks to a local Ollama HTTP API. Supports streaming generation and tool calls,
plus embeddings for semantic memory.

Ollama API docs: the model is pulled via `ollama pull <name>` first. We assume
the user has the model available; is_available() checks reachability.

See ARCHITECTURE.md §4.1.
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


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b-instruct",
        embedding_model: str = "nomic-embed-text",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embedding_model = embedding_model
        self.timeout = timeout

    async def is_available(self) -> bool:
        """Check the Ollama API is up and our model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # List local models.
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                models = {m.get("name", "") for m in resp.json().get("models", [])}
                # Accept the configured model name, with or without a :tag.
                return any(self.model.split(":")[0] in m for m in models)
        except (httpx.HTTPError, OSError) as e:
            logger.debug("ollama not available: %s", e)
            return False

    async def generate_stream(
        self, messages: list[Message], opts: GenerateOptions
    ) -> AsyncIterator[GenerateChunk]:
        """Stream a chat completion from Ollama.

        Ollama's /api/chat streams NDJSON; each line is a chunk with a message
        field. Tool calls arrive inside the model's content as JSON when the
        model is given tools in the request.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._serialize_message(m) for m in messages],
            "stream": True,
            "options": {
                "temperature": opts.temperature,
                "num_predict": opts.max_tokens,
            },
        }
        if opts.stop:
            payload["options"]["stop"] = opts.stop
        if opts.allow_tools and opts.tools:
            # Convert our generic tool schema to Ollama's format.
            payload["tools"] = [self._to_ollama_tool(t) for t in opts.tools]

        url = f"{self.base_url}/api/chat"

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
                        async with client.stream("POST", url, json=payload) as resp:
                            if resp.status_code != 200:
                                body = await resp.aread()
                                if 500 <= resp.status_code < 600:
                                    raise LLMRetryableError(
                                        f"ollama /api/chat returned {resp.status_code}: {body[:500]!r}"
                                    )
                                raise LLMUnavailableError(
                                    f"ollama /api/chat returned {resp.status_code}: {body[:500]!r}"
                                )
                            accumulated = ""
                            emitted_tool_call = False
                            async for line in resp.aiter_lines():
                                if not line:
                                    continue
                                try:
                                    chunk_json = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                msg = chunk_json.get("message", {}) or {}
                                content = msg.get("content", "") or ""
                                tool_calls = msg.get("tool_calls") or []

                                # Emit any tool calls as separate chunks.
                                for tc in tool_calls:
                                    emitted_tool_call = True
                                    args = tc.get("function", {}).get("arguments", tc.get("arguments", {}))
                                    yield GenerateChunk(
                                        tool_call={
                                            "id": tc.get("id", "") or f"call_{len(accumulated)}",
                                            "name": tc.get("function", {}).get("name") or tc.get("name", ""),
                                            "arguments": args if isinstance(args, dict) else _safe_json(args),
                                        }
                                    )

                                if content:
                                    accumulated += content
                                    # Some local models emit tool calls as JSON inside content
                                    # rather than via the tools API. Try to detect that.
                                    parsed = _maybe_extract_tool_call(accumulated)
                                    if parsed:
                                        yield GenerateChunk(tool_call=parsed, done=True, finish_reason="tool_use")
                                        return
                                    yield GenerateChunk(text=content)

                                if chunk_json.get("done"):
                                    finish = "tool_use" if (emitted_tool_call or tool_calls) else "stop"
                                    yield GenerateChunk(done=True, finish_reason=finish)
                                    return
                except httpx.ConnectError as e:
                    raise LLMRetryableError(
                        "Ollama is not running. Install Ollama from https://ollama.ai "
                        "and pull a model (e.g., `ollama pull llama3.2`). "
                        f"Connection to {self.base_url} failed."
                    ) from e
                except httpx.HTTPError as e:
                    raise LLMRetryableError(f"Ollama request failed: {e}") from e

                # Stream ended without an explicit done flag.
                yield GenerateChunk(done=True, finish_reason="stop")

    async def embed(self, text: str) -> list[float]:
        payload = {"model": self.embedding_model, "input": text}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/embed", json=payload)
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings") or data.get("embedding") or []
                if embeddings and isinstance(embeddings[0], list):
                    return embeddings[0]
                return embeddings
        except httpx.ConnectError as e:
            raise LLMUnavailableError(
                "Ollama is not running. Install Ollama from https://ollama.ai "
                f"to enable AI features. Connection to {self.base_url} failed."
            ) from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Ollama embed failed: {e}") from e

    # --- Serialization helpers -------------------------------------------

    def _serialize_message(self, m: Message) -> dict[str, Any]:
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc.get("arguments", {}))},
                }
                for tc in m.tool_calls
            ]
        return out

    def _to_ollama_tool(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Convert our generic tool schema to Ollama's function-tool format."""
        params = schema.get("parameters", {}) or {}
        return {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": params,
            },
        }


def _safe_json(s: Any) -> dict[str, Any]:
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


def _maybe_extract_tool_call(text: str) -> dict[str, Any] | None:
    """Detect a tool call serialized as JSON inside model text output.

    Local models sometimes emit a ```json ... ``` block with a {"tool": ..., "arguments": ...}
    object instead of using the tools API. We look for that pattern.
    """
    import re

    # Pattern 1: fenced ```json block containing a tool call.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fence.group(1)] if fence else []
    # Pattern 2: a bare {"tool": ...} / {"name": ...} object anywhere.
    bare = re.search(r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}', text, re.DOTALL)
    if bare:
        candidates.append(bare.group(0))

    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        name = obj.get("tool") or obj.get("name")
        if name:
            args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            return {"id": f"call_{abs(hash(name)) % 10**10}", "name": name, "arguments": args}
    return None
