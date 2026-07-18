"""Model metadata schema — version tracking for trained micro-models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

ModelStatus = str
STATUS_CANDIDATE = "candidate"
STATUS_PRODUCTION = "production"
STATUS_DEPRECATED = "deprecated"


@dataclass
class ModelMetadata:
    name: str
    version: str
    model_type: str  # "intent_classifier" | "tool_selector" | "memory_retrieval" | "intent_router" | "error_recovery" | "planning"
    created_at: str = ""
    dataset_hash: str = ""
    dataset_size: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    benchmark_results: dict[str, Any] = field(default_factory=dict)
    status: ModelStatus = STATUS_CANDIDATE
    path: str = ""
    parent_version: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "model_type": self.model_type,
            "created_at": self.created_at,
            "dataset_hash": self.dataset_hash,
            "dataset_size": self.dataset_size,
            "metrics": self.metrics,
            "benchmark_results": self.benchmark_results,
            "status": self.status,
            "path": self.path,
            "parent_version": self.parent_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelMetadata:
        return cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            model_type=data.get("model_type", ""),
            created_at=data.get("created_at", ""),
            dataset_hash=data.get("dataset_hash", ""),
            dataset_size=data.get("dataset_size", 0),
            metrics=data.get("metrics", {}),
            benchmark_results=data.get("benchmark_results", {}),
            status=data.get("status", STATUS_CANDIDATE),
            path=data.get("path", ""),
            parent_version=data.get("parent_version", ""),
        )
