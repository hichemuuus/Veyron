"""Tool selection model — predicts required tools from user requests.

Exports:
  - ToolSelectorModel: trainable multi-label classifier
  - ToolSelectionDataset: training data management
  - ToolSelectionMetrics: evaluation metrics
  - train_tool_selector: training pipeline
"""

from paios.intelligence.tool_selector.schema import ToolSelectionExample, ToolPrediction
from paios.intelligence.tool_selector.dataset import ToolSelectionDataset
from paios.intelligence.tool_selector.metrics import ToolSelectionMetrics
from paios.intelligence.tool_selector.model import ToolSelectorModel
from paios.intelligence.tool_selector.trainer import train_tool_selector
