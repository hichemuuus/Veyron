"""Model registry — tracks versions, manages production selection, safe loading."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from veyron.config import DATA_DIR
from veyron.intelligence.models.schema import (
    STATUS_CANDIDATE,
    STATUS_DEPRECATED,
    STATUS_PRODUCTION,
    ModelMetadata,
)

logger = logging.getLogger(__name__)

MODELS_DIR = DATA_DIR / "models"
REGISTRY_FILE = MODELS_DIR / "model_registry.json"


class ModelRegistry:
    def __init__(self, registry_path: str | Path | None = None) -> None:
        self._registry_path = Path(registry_path or REGISTRY_FILE)
        self._models: dict[str, dict[str, ModelMetadata]] = {}  # model_type -> {version -> metadata}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self._registry_path.exists():
            self._models = {}
            return
        try:
            with open(self._registry_path, encoding="utf-8") as f:
                raw: dict[str, dict[str, dict[str, Any]]] = json.load(f)
            self._models = {}
            for model_type, versions in raw.items():
                self._models[model_type] = {
                    v: ModelMetadata.from_dict(d) for v, d in versions.items()
                }
        except Exception as e:
            logger.warning("failed to load model registry: %s", e)
            self._models = {}

    def _save(self) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        raw: dict[str, dict[str, dict[str, Any]]] = {}
        for model_type, versions in self._models.items():
            raw[model_type] = {v: md.to_dict() for v, md in versions.items()}
        with open(self._registry_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)

    def register(self, metadata: ModelMetadata) -> ModelMetadata:
        with self._lock:
            model_type = metadata.model_type
            if model_type not in self._models:
                self._models[model_type] = {}
            self._models[model_type][metadata.version] = metadata
            self._save()
            logger.info(
                "registered model %s v%s (%s)",
                metadata.name, metadata.version, metadata.status,
            )
        return metadata

    def promote(self, model_type: str, version: str) -> ModelMetadata | None:
        with self._lock:
            versions = self._models.get(model_type, {})
            if version not in versions:
                logger.warning("cannot promote %s v%s: not found", model_type, version)
                return None
            for v, md in versions.items():
                if md.status == STATUS_PRODUCTION:
                    md.status = STATUS_DEPRECATED
            target = versions[version]
            target.status = STATUS_PRODUCTION
            self._save()
            logger.info("promoted %s v%s to production", model_type, version)
        return target

    def rollback(self, model_type: str, version: str) -> ModelMetadata | None:
        with self._lock:
            versions = self._models.get(model_type, {})
            if version not in versions:
                logger.warning("cannot rollback %s to v%s: not found", model_type, version)
                return None
            for v, md in versions.items():
                md.status = STATUS_DEPRECATED if md.status == STATUS_PRODUCTION else md.status
            target = versions[version]
            target.status = STATUS_PRODUCTION
            self._save()
            logger.info("rolled back %s to v%s", model_type, version)
        return target

    def get_production(self, model_type: str) -> ModelMetadata | None:
        versions = self._models.get(model_type, {})
        for md in versions.values():
            if md.status == STATUS_PRODUCTION:
                return md
        return None

    def get_production_model(self, name: str) -> dict[str, Any] | None:
        """Return path and metadata for the production model with the given name.

        Args:
            name: Model type name (e.g. ``"intent_classifier"``, ``"tool_selector"``).

        Returns:
            Dict with ``"path"`` and ``"metadata"`` keys, or None if no
            production model is registered.
        """
        md = self.get_production(name)
        if md is None:
            return None
        return {"path": md.path, "metadata": md.to_dict()}

    def get(self, model_type: str, version: str) -> ModelMetadata | None:
        return self._models.get(model_type, {}).get(version)

    def list_models(self, model_type: str | None = None) -> list[ModelMetadata]:
        result: list[ModelMetadata] = []
        for mt, versions in self._models.items():
            if model_type and mt != model_type:
                continue
            result.extend(versions.values())
        return sorted(result, key=lambda m: m.created_at, reverse=True)

    def load_production_model(self, model_type: str):
        """Load the production model for a given type. Returns None if no production model."""
        md = self.get_production(model_type)
        if md is None:
            logger.warning("no production %s model found", model_type)
            return None
        path = Path(md.path)
        if not path.exists():
            logger.warning("production %s model file missing: %s", model_type, path)
            return None
        try:
            if model_type == "intent_classifier":
                from veyron.intelligence.intent.model import IntentModel
                model = IntentModel()
                model.load(str(path))
                return model
            elif model_type == "tool_selector":
                from veyron.intelligence.tool_selector.model import ToolSelectorModel
                model = ToolSelectorModel()
                model.load(str(path))
                return model
            elif model_type == "memory_retrieval":
                from veyron.intelligence.memory_retrieval.model import MemoryRetrievalModel
                model = MemoryRetrievalModel()
                model.load(str(path))
                return model
            elif model_type == "intent_router":
                from veyron.intelligence.intent_router.model import IntentRouterModel
                model = IntentRouterModel()
                model.load(str(path))
                return model
            elif model_type == "error_recovery":
                from veyron.intelligence.error_recovery.model import ErrorRecoveryModel
                model = ErrorRecoveryModel()
                model.load(str(path))
                return model
            elif model_type == "planning":
                from veyron.intelligence.planning.model import PlanningModel
                model = PlanningModel()
                model.load(str(path))
                return model
            else:
                logger.warning("unknown model type: %s", model_type)
                return None
        except Exception as e:
            logger.error("failed to load production %s model: %s", model_type, e)
            return None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for model_type, versions in self._models.items():
            result[model_type] = {
                "production": None,
                "candidates": [],
                "deprecated": [],
            }
            for v, md in versions.items():
                entry = {"version": v, "created_at": md.created_at, "metrics": md.metrics}
                if md.status == STATUS_PRODUCTION:
                    result[model_type]["production"] = entry
                elif md.status == STATUS_CANDIDATE:
                    result[model_type]["candidates"].append(entry)
                elif md.status == STATUS_DEPRECATED:
                    result[model_type]["deprecated"].append(entry)
        return result

    @property
    def registry_path(self) -> Path:
        return self._registry_path


_registry: ModelRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ModelRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
