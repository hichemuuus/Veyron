"""PAIOS intelligence layer — Tier-1 micro-models for routing and reasoning.

Intended to handle high-confidence, narrow-domain tasks without invoking the
full LLM. Falls back gracefully when confidence is low.
"""

from paios.intelligence.intent.inference import classify_intent as classify_intent
from paios.intelligence.intent.model import IntentModel as IntentModel
from paios.intelligence.intent.dataset import IntentDataset as IntentDataset
from paios.intelligence.tool_selector.model import ToolSelectorModel as ToolSelectorModel
