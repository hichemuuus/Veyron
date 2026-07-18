"""Skill store — persist and manage detected skills."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlmodel import select, delete, update, func

from veyron.db.base import sync_session_scope
from veyron.db.models import Skill
from veyron.learning.skill_detector import DetectedSkill, SkillDetector

logger = logging.getLogger(__name__)


class SkillStore:
    """Persistent storage for detected skills."""

    def save_skill(self, detected: DetectedSkill) -> Skill:
        """Save a detected skill to the database."""
        with sync_session_scope() as session:
            existing = session.exec(select(Skill).where(Skill.name == detected.name)).first()
            if existing:
                existing.frequency = detected.frequency
                existing.confidence = detected.confidence
                existing.pattern_steps = json.dumps(detected.steps)
                existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(existing)
                session.flush()
                session.refresh(existing)
                logger.info("updated skill: %s (freq=%d)", existing.name, existing.frequency)
                return existing

            skill = Skill(
                public_id=str(uuid4()),
                name=detected.name,
                description=detected.description,
                pattern_steps=json.dumps(detected.steps),
                frequency=detected.frequency,
                confidence=detected.confidence,
                enabled=True,
            )
            session.add(skill)
            session.flush()
            session.refresh(skill)
            logger.info("saved skill: %s (freq=%d)", skill.name, skill.frequency)
            return skill

    def get_skill(self, public_id: str) -> Skill | None:
        with sync_session_scope() as session:
            return session.exec(select(Skill).where(Skill.public_id == public_id)).first()

    def get_skill_by_name(self, name: str) -> Skill | None:
        with sync_session_scope() as session:
            return session.exec(select(Skill).where(Skill.name == name)).first()

    def list_skills(self, enabled_only: bool = True, limit: int = 50, offset: int = 0) -> list[Skill]:
        with sync_session_scope() as session:
            stmt = select(Skill)
            if enabled_only:
                stmt = stmt.where(Skill.enabled == True)
            return session.exec(stmt.order_by(Skill.frequency.desc()).offset(offset).limit(limit)).all()

    def delete_skill(self, public_id: str) -> bool:
        with sync_session_scope() as session:
            skill = session.exec(select(Skill).where(Skill.public_id == public_id)).first()
            if not skill:
                return False
            session.delete(skill)
            return True

    def toggle_skill(self, public_id: str, enabled: bool) -> Skill | None:
        with sync_session_scope() as session:
            skill = session.exec(select(Skill).where(Skill.public_id == public_id)).first()
            if not skill:
                return None
            skill.enabled = enabled
            skill.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(skill)
            session.flush()
            session.refresh(skill)
            return skill

    def run_detection(self, task_history: list[dict] | None = None) -> list[Skill]:
        """Run skill detection and save new skills."""
        detector = SkillDetector()
        detected = detector.detect_skills()
        if task_history:
            detected.extend(detector.detect_skills_from_tasks(task_history))
        saved: list[Skill] = []
        for d in detected:
            saved.append(self.save_skill(d))
        logger.info("skill detection: %d new/updated skills", len(saved))
        return saved

    def get_skill_stats(self) -> dict:
        with sync_session_scope() as session:
            total = len(session.exec(select(Skill)).all())
            enabled = len(session.exec(select(Skill).where(Skill.enabled == True)).all())
            avg_conf = session.exec(select(Skill.confidence)).all()
            avg_conf_val = sum(c[0] for c in avg_conf) / len(avg_conf) if avg_conf else 0
            top = session.exec(select(Skill).order_by(Skill.frequency.desc()).limit(5)).all()
            return {
                "total": total,
                "enabled": enabled,
                "average_confidence": round(avg_conf_val, 4),
                "top_skills": [{"name": s.name, "frequency": s.frequency, "confidence": s.confidence} for s in top],
            }


# Singleton
_store: SkillStore | None = None


def get_skill_store() -> SkillStore:
    global _store
    if _store is None:
        _store = SkillStore()
    return _store


def reset_skill_store() -> None:
    global _store
    _store = None
