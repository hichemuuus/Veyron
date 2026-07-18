"""Intelligence scheduler — background retraining loop.

Periodically checks dataset growth, triggers retraining in a subprocess,
and logs output.  The subprocess approach keeps the API responsive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any

from veyron.config import DATA_DIR, get_settings
from veyron.intelligence.training.dataset import (
    USER_INTERACTIONS_DIR,
    TrainingDataset,
    load_user_interactions,
)
from veyron.intelligence.training.retrain import (
    DatasetGrowthDetector,
    RetrainingOrchestrator,
)
# Lazy import: get_skill_store (avoid circular with learning modules)
from veyron.memory.store import get_memory_store

logger = logging.getLogger(__name__)

_LOCK_FILE = DATA_DIR / "training.lock"
_TRAINING_LOG = DATA_DIR / "logs" / "training_output.log"


class IntelligenceScheduler:
    """Background scheduler that periodically checks retraining conditions.

    Runs an asyncio loop at a configurable interval. Each cycle:
      1. Checks if the training dataset has grown enough
      2. If triggered: spawns a subprocess to train + benchmark + promote
    """

    def __init__(
        self,
        interval_seconds: int = 300,
        retrain_min_growth_pct: float = 10.0,
    ) -> None:
        self._interval = interval_seconds
        self._growth_detector = DatasetGrowthDetector(min_growth_pct=retrain_min_growth_pct)
        self._orchestrator = RetrainingOrchestrator()
        self._task: asyncio.Task | None = None
        self._auto_improvement_task: asyncio.Task | None = None
        self._running = False
        self._last_train_count = 0
        self._last_cycle_at: float | None = None
        self._current_cycle_errors: list[str] = []
        self._is_training = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_training(self) -> bool:
        return self._is_training

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        self._auto_improvement_task = asyncio.create_task(self._run_auto_improvement_loop())
        logger.info("scheduler started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._auto_improvement_task is not None:
            self._auto_improvement_task.cancel()
            try:
                await self._auto_improvement_task
            except asyncio.CancelledError:
                pass
            self._auto_improvement_task = None
        logger.info("scheduler stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("scheduler cycle failed: %s", e)
            await asyncio.sleep(self._interval)

    async def _cycle(self) -> None:
        """Run one scheduler cycle."""
        if self.is_training:
            logger.info("scheduler: training already in progress, skipping cycle")
            self._last_cycle_at = time.time()
            return

        interactions = load_user_interactions()
        if not interactions:
            self._last_cycle_at = time.time()
            self._current_cycle_errors = []
            return

        dataset = TrainingDataset([ui.to_training_example() for ui in interactions])
        dataset = dataset.deduplicate()
        current_size = len(dataset)

        if not self._growth_detector.should_retrain(current_size, self._last_train_count):
            logger.debug(
                "scheduler: growth below threshold (%d < %d + %.0f%%)",
                current_size, self._last_train_count, self._growth_detector.min_growth_pct,
            )
            self._last_cycle_at = time.time()
            self._current_cycle_errors = []
            return

        logger.info(
            "scheduler: dataset grew %d -> %d, spawning training subprocess",
            self._last_train_count, current_size,
        )

        # Acquire file lock to prevent concurrent training.
        if not self._acquire_lock():
            logger.warning("scheduler: training already locked by another process, skipping cycle")
            self._last_cycle_at = time.time()
            self._current_cycle_errors = []
            return
        _TRAINING_LOG.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._is_training = True
            logger.info("scheduler: spawning training subprocess")

            def _run_training() -> int:
                """Run training in a subprocess (called from thread pool)."""
                import subprocess as _sp
                log_path = str(_TRAINING_LOG)
                kwargs: dict[str, Any] = {}
                if sys.platform.startswith("win"):
                    kwargs["creationflags"] = _sp.CREATE_NO_WINDOW
                with open(log_path, "ab") as _lf:
                    result = _sp.run(
                        [sys.executable, "-m", "veyron.intelligence.training.subprocess_train",
                         "--interactions-dir", str(USER_INTERACTIONS_DIR)],
                        stdout=_lf, stderr=_lf, **kwargs,
                    )
                return result.returncode

            loop = asyncio.get_event_loop()
            returncode = await loop.run_in_executor(None, _run_training)

            if returncode == 0:
                logger.info("scheduler: training subprocess completed successfully")
            else:
                msg = f"training subprocess exited with code {returncode}"
                self._current_cycle_errors.append(msg)
                logger.warning("scheduler: %s", msg)
        except Exception as e:
            self._current_cycle_errors.append(f"subprocess: {e}")
            logger.exception("scheduler: failed to spawn training subprocess")
        finally:
            self._is_training = False
            self._release_lock()

        self._last_train_count = current_size
        self._last_cycle_at = time.time()
        self._current_cycle_errors = []

    def _acquire_lock(self) -> bool:
        """Create the training lock file atomically. Returns True if acquired."""
        _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            return False
        except OSError:
            return False

    @staticmethod
    def _release_lock() -> None:
        try:
            if _LOCK_FILE.exists():
                _LOCK_FILE.unlink()
        except Exception:
            pass

    @property
    def _is_locked(self) -> bool:
        return _LOCK_FILE.exists()

    # ── Auto-improvement cycle ──────────────────────────────────────────

    async def _run_auto_improvement_loop(self) -> None:
        """Background loop that periodically runs auto-improvement tasks."""
        while self._running:
            try:
                await self._auto_improvement_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("auto-improvement cycle failed: %s", e)
            interval = get_settings().model.auto_improvement_interval_seconds
            await asyncio.sleep(interval)

    async def _auto_improvement_cycle(self) -> None:
        """Run skill detection, memory health, dataset quality, and log findings."""
        findings: list[str] = []

        # Skill detection.
        try:
            from veyron.learning.skill_store import get_skill_store
            skill_store = get_skill_store()
            skills = await asyncio.to_thread(skill_store.run_detection)
            if skills:
                findings.append(f"detected {len(skills)} new/updated skills")
        except Exception as e:
            msg = f"skill_detection: {e}"
            self._current_cycle_errors.append(msg)
            logger.warning("auto-improvement: %s", msg)

        # Memory health.
        try:
            memory_store = get_memory_store()
            stats = await asyncio.to_thread(memory_store.run_maintenance)
            decayed = stats.get("decayed", 0)
            deleted = stats.get("deleted", 0)
            if decayed > 0 or deleted > 0:
                findings.append(f"memory maintenance: {decayed} decayed, {deleted} deleted")
        except Exception as e:
            msg = f"memory_maintenance: {e}"
            self._current_cycle_errors.append(msg)
            logger.warning("auto-improvement: %s", msg)

        # Dataset quality.
        try:
            interactions = load_user_interactions()
            if interactions:
                dataset = TrainingDataset([ui.to_training_example() for ui in interactions])
                quality = await asyncio.to_thread(
                    self._orchestrator.assess_dataset_quality, dataset,
                )
                if quality.suggested_actions:
                    findings.append(
                        "dataset quality: " + "; ".join(quality.suggested_actions),
                    )
        except Exception as e:
            msg = f"dataset_quality: {e}"
            self._current_cycle_errors.append(msg)
            logger.warning("auto-improvement: %s", msg)

        # Log notable findings as learning events.
        if findings:
            try:
                await asyncio.to_thread(
                    self._orchestrator.record_learning_event,
                    "auto_improvement",
                    "system",
                    "; ".join(findings),
                    {"findings": findings},
                )
            except Exception as e:
                logger.warning("auto-improvement: failed to record learning event: %s", e)

        if findings:
            logger.info("auto-improvement cycle: %s", "; ".join(findings))

    # ── Status ──────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current scheduler status.

        Returns:
            Dict with keys: is_running, last_cycle_at, interval_seconds,
            model_versions, dataset_growth, last_train_count,
            current_cycle_errors.
        """
        from veyron.intelligence.models.registry import ModelRegistry

        registry = ModelRegistry()
        models = registry.list_models()
        model_versions: dict[str, list[dict]] = {}
        for m in models:
            mt = m.model_type
            if mt not in model_versions:
                model_versions[mt] = []
            entry = {
                "version": m.version,
                "status": m.status,
                "metrics": m.metrics,
                "created_at": m.created_at,
            }
            if m.status == "production":
                model_versions[mt].insert(0, entry)
            else:
                model_versions[mt].append(entry)

        # Compute current dataset growth versus last training count.
        try:
            interactions = load_user_interactions()
            current_size = len(interactions)
            if self._last_train_count > 0 and current_size > 0:
                growth_pct = round(
                    (current_size - self._last_train_count)
                    / self._last_train_count * 100, 1,
                )
            else:
                growth_pct = 0.0
            dataset_growth = {
                "current_size": current_size,
                "last_train_size": self._last_train_count,
                "growth_pct": growth_pct,
            }
        except Exception:
            dataset_growth = {"error": "unable to compute"}

        return {
            "is_running": self._running,
            "is_training": self.is_training,
            "interval_seconds": self._interval,
            "last_cycle_at": self._last_cycle_at,
            "model_versions": model_versions,
            "dataset_growth": dataset_growth,
            "last_train_count": self._last_train_count,
            "current_cycle_errors": list(self._current_cycle_errors),
        }

    # ── Manual trigger ──────────────────────────────────────────────────

    def trigger_now(self) -> None:
        """Force an immediate scheduler cycle.

        Cancels the current sleep wait and starts a fresh run loop so the
        next cycle begins immediately.
        """
        if self._running and self._task is not None:
            self._task.cancel()
            self._task = asyncio.create_task(self._run_loop())
            logger.info("scheduler: manual trigger — cycle restarted")
