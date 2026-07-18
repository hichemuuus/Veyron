"""LLM provider abstraction.

The agent talks to an LLMProvider, never a concrete backend. This keeps
OpenAI / Anthropic / Ollama / a cloud API swappable without touching the agent.

See ARCHITECTURE.md §4 and DECISIONS.md (MODEL STRATEGY).
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single chat message."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # For role="tool": the tool name and call id that produced this content.
    tool_name: str | None = None
    tool_call_id: str | None = None
    # For role="assistant": tool calls the model emitted.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GenerateOptions:
    temperature: float = 0.2
    max_tokens: int = 1024
    # Tools made available to the model (JSON-Schema descriptions).
    tools: list[dict[str, Any]] = field(default_factory=list)
    # If True, the model may emit tool calls; else tools are ignored.
    allow_tools: bool = True
    # Provider-specific stop sequences.
    stop: list[str] = field(default_factory=list)


@dataclass
class GenerateChunk:
    """One streamed chunk of a generation."""

    # Incremental text delta (may be empty).
    text: str = ""
    # A complete tool call (set when the model emits one). Format:
    # {"id": str, "name": str, "arguments": dict}
    tool_call: dict[str, Any] | None = None
    # Set True on the final chunk.
    done: bool = False
    # Finish reason on the final chunk: "stop" | "tool_use" | "length" | "error".
    finish_reason: str | None = None


class LLMProvider(ABC):
    """Interface every backend implements."""

    name: str = "base"

    @abstractmethod
    async def generate_stream(
        self, messages: list[Message], opts: GenerateOptions
    ) -> AsyncIterator[GenerateChunk]:
        """Stream a generation. Yields chunks until a final done=True chunk."""
        ...
        # yield is required to make this an async generator; pragma below silences lint
        if False:
            yield GenerateChunk()  # pragma: no cover

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return an embedding vector for semantic memory (Phase 2)."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if the backend is reachable and ready."""
        ...


class LLMUnavailableError(RuntimeError):
    """Raised when the configured provider can't be reached."""


class LLMRetryableError(LLMUnavailableError):
    """Transient error that should be retried (connection issues, 5xx, etc.)."""


class FallbackProvider(LLMProvider):
    """Wraps a primary provider with an optional remote fallback.

    On LLMUnavailableError from the primary, transparently falls back
    to the secondary provider. This keeps the agent running even when
    the local model (Ollama) is down.
    """

    name = "fallback"

    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    async def generate_stream(
        self, messages: list[Message], opts: GenerateOptions
    ) -> AsyncIterator[GenerateChunk]:
        try:
            async for chunk in self.primary.generate_stream(messages, opts):
                yield chunk
        except LLMUnavailableError as e:
            if self.fallback is None:
                raise
            logger.info("primary provider unavailable, falling back to %s: %s", self.fallback.name, e)
            async for chunk in self.fallback.generate_stream(messages, opts):
                yield chunk

    async def embed(self, text: str) -> list[float]:
        try:
            return await self.primary.embed(text)
        except LLMUnavailableError as e:
            if self.fallback is None:
                raise
            logger.info("primary embed failed, falling back to %s: %s", self.fallback.name, e)
            return await self.fallback.embed(text)

    async def is_available(self) -> bool:
        primary_ok = await self.primary.is_available()
        if primary_ok:
            return True
        if self.fallback is not None:
            return await self.fallback.is_available()
        return False


# Process-wide provider.
_provider: LLMProvider | None = None
_provider_lock = threading.Lock()


def _build_provider() -> LLMProvider:
    """Build the provider chain: primary (Ollama) + optional remote fallback."""
    from veyron.config import get_settings
    from veyron.llm.ollama import OllamaProvider

    settings = get_settings()

    primary: LLMProvider = OllamaProvider(
        base_url=settings.model.ollama_url,
        model=settings.model.base_model,
        embedding_model=settings.model.embedding_model,
    )

    fallback: LLMProvider | None = None
    if settings.model.remote_enabled and settings.model.remote_url and settings.model.remote_api_key:
        from veyron.llm.remote import RemoteProvider

        fallback = RemoteProvider(
            base_url=settings.model.remote_url,
            api_key=settings.model.remote_api_key,
            model=settings.model.remote_model,
            embedding_model=settings.model.remote_embedding_model,
        )

    return FallbackProvider(primary=primary, fallback=fallback)


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = _build_provider()
    return _provider


async def check_provider_available() -> bool:
    """Check whether the configured provider is reachable.

    Used at startup and before agent runs. Returns True if any provider
    in the chain is reachable. Raises LLMUnavailableError only when
    require_local_model is True AND no fallback provider is configured.
    """
    provider = get_provider()
    try:
        available = await provider.is_available()
    except Exception as e:
        available = False
        logger.warning("provider availability check failed: %s", e)

    if not available:
        from veyron.config import get_settings

        settings = get_settings()
        has_fallback = bool(settings.model.remote_enabled and settings.model.remote_url and settings.model.remote_api_key)

        if settings.model.require_local_model and not has_fallback:
            raise LLMUnavailableError(
                f"LLM provider '{provider.name}' is not available and require_local_model is enabled. "
                f"Ensure {get_settings().model.base_model} is pulled in Ollama, "
                f"or configure a remote fallback provider."
            )
    return available


def set_provider(provider: LLMProvider) -> None:
    """Inject a provider (testing or swapping backends)."""
    global _provider
    _provider = provider


def reset_provider() -> None:
    global _provider
    _provider = None
