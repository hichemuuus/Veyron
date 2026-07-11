"""Tool selection schema — defines what the future tool-selection model predicts.

The model should take a user request and predict:
  - Which tool(s) are needed (ordered by relevance)
  - A confidence score per tool
  - What information is missing (e.g. file path, command arguments)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paios.tools.registry import get_registry


@dataclass
class ToolPrediction:
    """A single tool prediction from the selection model."""

    tool_name: str
    confidence: float
    # Parameters the model predicts should be passed to this tool.
    predicted_params: dict[str, Any] = field(default_factory=dict)
    # Any required inputs that the model couldn't extract from the request.
    missing_parameters: list[str] = field(default_factory=list)


@dataclass
class ToolSelectionResult:
    """Full output of the tool-selection model for one request."""

    request: str
    predictions: list[ToolPrediction]
    # Whether the model is confident enough to bypass the LLM for tool selection.
    bypasses_llm: bool = False


_TOOL_NAMES: list[str] = []


def available_tool_names() -> list[str]:
    """Return the names of all registered tools (cached)."""
    global _TOOL_NAMES
    if not _TOOL_NAMES:
        _TOOL_NAMES = get_registry().names()
    return _TOOL_NAMES


@dataclass
class ToolSelectionExample:
    """A single training example for the tool-selection model.

    This is the interchange format between dataset generation and model training.
    """

    text: str
    # The tool(s) a human expert would select, in priority order.
    expected_tools: list[str]
    # Intent category (from the intent classifier) for context.
    intent_category: str = ""
    # Free-form notes about what the tool should do.
    notes: str = ""


def example_to_prediction_target(example: ToolSelectionExample) -> dict[str, Any]:
    """Convert a ToolSelectionExample to a model-compatible target dict."""
    return {
        "text": example.text,
        "tools": example.expected_tools,
        "intent": example.intent_category,
    }
