"""Intent classification — route user requests to the correct handler.

Exports:
  - IntentModel: model interface (can be trained with sklearn)
  - IntentDataset: dataset generation and loading
  - train_model: training pipeline
  - classify_intent: inference entrypoint
"""

from paios.intelligence.intent.model import IntentModel
from paios.intelligence.intent.dataset import IntentDataset
from paios.intelligence.intent.trainer import train_model
from paios.intelligence.intent.inference import classify_intent, ClassifierResult
