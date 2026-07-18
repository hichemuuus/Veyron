"""Veyron configuration.

Loads settings from (in order of precedence):
   1. Environment variables (VEYRON_* prefix, case-insensitive)
  2. .env file in the project root
  3. config.yaml in the project root
  4. Built-in defaults

All tunable values live here. See DECISIONS.md for the rationale behind defaults.
"""

from __future__ import annotations

import enum
import os
import sys as _sys
from functools import lru_cache
from pathlib import Path
from typing import Literal


class ApprovalMode(str, enum.Enum):
    """How the system handles approval for non-FREE actions."""
    AUTONOMOUS = "autonomous"
    CONFIRM = "confirm"
    SAFE = "safe"


class RiskLevel(str, enum.Enum):
    """Risk classification for tool actions.
    
    Ordering: LOW (0) < MEDIUM (1) < HIGH (2) < CRITICAL (3).
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def severity(self) -> int:
        """Numeric severity for comparison."""
        return _SEVERITY_MAP[self]


_SEVERITY_MAP: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Path resolution ──────────────────────────────────────────────────
# When running as a PyInstaller binary the extraction directory is
# ephemeral — use %APPDATA%/Veyron/veyron-data for persistence across
# updates.  In development, use the project-relative location.

_IS_FROZEN = getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

if _IS_FROZEN:
    _base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Veyron"
    DATA_DIR = _base / "veyron-data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DATA_DIR = BACKEND_ROOT / "data"


class SecurityConfig(BaseSettings):
    """Security-related settings."""

    # Filesystem roots the AI is allowed to touch. Defaults to the user's home
    # directory and the project root. Customize in config.yaml.
    sandbox_roots: list[str] = Field(default_factory=list)

    # Timeout (seconds) for user confirmation of CONFIRM-level actions.
    confirm_timeout_seconds: int = 120

    # Max iterations of the ReAct loop before the agent gives up.
    agent_max_iterations: int = 12

    # Max characters of tool output fed back into the agent context.
    max_tool_output_chars: int = 8000

    # Safety policy settings.
    approval_mode: str = "confirm"  # autonomous | confirm | safe
    max_auto_risk: str = "low"      # highest risk auto-approved in AUTONOMOUS mode
    require_confirm_risk: str = "medium"  # risk threshold for confirmation in CONFIRM mode

    # Reflection.
    reflection_enabled: bool = True  # run post-task reflection analysis


class ModelConfig(BaseSettings):
    """Tier-2 (base) and Tier-1 (micro) model settings."""

    # Ollama base URL.
    ollama_url: str = "http://localhost:11434"

    # Default base model. See DECISIONS.md for rationale.
    base_model: str = "qwen2.5:3b-instruct"

    # Embedding model for semantic memory (Phase 2).
    embedding_model: str = "nomic-embed-text"

    # Generation defaults.
    temperature: float = 0.2
    max_tokens: int = 1024

    # Reflection sampling: fraction of successful tasks to reflect on.
    # Always reflects on failures regardless of this rate.
    reflection_sample_rate: float = 0.2

    # If True and Ollama is unreachable, the agent returns a clear error rather
    # than attempting a fallback. Flip to enable cloud fallback later.
    require_local_model: bool = True

    # Micro-model (Tier-1) settings.
    micro_models_enabled: bool = False
    micro_model_confidence_threshold: float = 0.7
    filter_tools_by_prediction: bool = True

    # Remote provider (fallback when the local model is unavailable).
    # Uses OpenAI-compatible API format (works with OpenAI, Together, Groq, etc.).
    remote_enabled: bool = False
    remote_url: str = ""
    remote_api_key: str = ""
    remote_model: str = "gpt-4o-mini"
    remote_embedding_model: str = "text-embedding-3-small"

    # Scheduler settings for background retraining.
    scheduler_interval_seconds: int = 300
    retrain_min_growth_pct: float = 10.0

    # Learning & Automation settings.
    auto_promote_models: bool = True  # auto-promote better models to production after training
    learning_enabled: bool = True
    reflection_store_enabled: bool = True
    skill_detection_enabled: bool = True
    skill_min_frequency: int = 3
    workflow_engine_enabled: bool = True
    plugin_system_enabled: bool = True
    auto_improvement_enabled: bool = True
    auto_improvement_interval_seconds: int = 3600
    benchmark_comparison_enabled: bool = True
    model_rollback_enabled: bool = True
    never_deploy_weaker: bool = True
    memory_importance_scoring_enabled: bool = True
    memory_duplicate_detection_enabled: bool = True
    memory_merging_enabled: bool = True
    memory_summarization_enabled: bool = True
    memory_decay_enabled: bool = True
    user_profile_enabled: bool = True
    user_profile_update_interval_hours: int = 24


class ServerConfig(BaseSettings):
    """HTTP server settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "tauri://localhost", "https://tauri.localhost"])
    # Serve the built frontend from this directory in production mode.
    frontend_dist: str = str(PROJECT_ROOT / "frontend" / "dist")
    # Bearer token for API authentication. If None, auth is disabled (dev mode).
    api_auth_token: str | None = None


class MonitorConfig(BaseSettings):
    """System monitoring settings."""

    cpu_interval: float = 0.2
    process_interval: float = 0.25
    memory_interval: float = 0.5
    disk_interval: float = 1.0
    network_interval: float = 0.5
    temp_interval: float = 1.0
    gpu_interval: float = 5.0
    top_n_processes: int = 30
    push_interval: float = 0.2
    enabled: bool = True


class Settings(BaseSettings):
    """Top-level Veyron settings."""

    model_config = SettingsConfigDict(
        env_prefix="VEYRON_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Literal["dev", "prod"] = "dev"

    # Database located under backend/data/ (gitignored).
    database_url: str | None = None  # computed lazily in get_settings()

    security: SecurityConfig = Field(default_factory=SecurityConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def _load_yaml_overrides() -> dict:
    """Load config.yaml if it exists; return a flat-ish dict for merging."""
    yaml_path = PROJECT_ROOT / "config.yaml"
    if not yaml_path.exists():
        return {}
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache the Settings object.

    Applies defaults → YAML → env (.env + process env). Nested sections in
    config.yaml (security, model, server) are merged into the corresponding
    sub-settings.
    """
    overrides = _load_yaml_overrides()

    # Expand default sandbox roots if none provided anywhere.
    home = str(Path.home())
    sec = overrides.get("security", {}) or {}
    if "sandbox_roots" not in sec:
        sec["sandbox_roots"] = [home, str(PROJECT_ROOT)]

    settings = Settings()
    # Compute database_url lazily so DATA_DIR can be redirected in tests.
    if settings.database_url is None:
        settings.database_url = f"sqlite:///{DATA_DIR / 'veyron.db'}"
    settings.security = SecurityConfig(**sec)
    if "model" in overrides:
        settings.model = ModelConfig(**(overrides["model"] or {}))
    if "server" in overrides:
        settings.server = ServerConfig(**(overrides["server"] or {}))
    if "monitor" in overrides:
        settings.monitor = MonitorConfig(**(overrides["monitor"] or {}))
    if "environment" in overrides:
        settings.environment = overrides["environment"]
    if "database_url" in overrides:
        settings.database_url = overrides["database_url"]

    return settings


def reset_settings_cache() -> None:
    """Test helper: clear the cached settings."""
    get_settings.cache_clear()
