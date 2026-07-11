"""LLM provider abstraction.

The agent talks to an LLMProvider, never a concrete backend. This keeps
OpenAI / Anthropic / Ollama / a cloud API swappable without touching the agent.

See ARCHITECTURE.md §4 and DECISIONS.md (MODEL STRATEGY).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class Message:
    """A single chat message."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # For role="tool": the tool name and call id that produced this content.
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
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
    tool_call: Optional[dict[str, Any]] = None
    # Set True on the final chunk.
    done: bool = False
    # Finish reason on the final chunk: "stop" | "tool_use" | "length" | "error".
    finish_reason: Optional[str] = None


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


# Process-wide provider.
_provider: LLMProvider | None = None
_provider_lock = threading.Lock()


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                from paios.config import get_settings

                from paios.llm.ollama import OllamaProvider

                settings = get_settings()
                _provider = OllamaProvider(
                    base_url=settings.model.ollama_url,
                    model=settings.model.base_model,
                    embedding_model=settings.model.embedding_model,
                )
    return _provider


async def check_provider_available() -> bool:
    """Check whether the configured provider is reachable.

    Used at startup and before agent runs. Returns False if the provider
    is unreachable, or raises LLMUnavailableError if require_local_model
    is enabled.
    """
    provider = get_provider()
    try:
        available = await provider.is_available()
    except Exception as e:
        available = False
        logger.warning("provider availability check failed: %s", e)

    if not available:
        from paios.config import get_settings

        if get_settings().model.require_local_model:
            raise LLMUnavailableError(
                f"LLM provider '{provider.name}' is not available and require_local_model is enabled. "
                f"Ensure {get_settings().model.base_model} is pulled in Ollama."
            )
    return available


def set_provider(provider: LLMProvider) -> None:
    """Inject a provider (testing or swapping backends)."""
    global _provider
    _provider = provider


def reset_provider() -> None:
    global _provider
    _provider = None
