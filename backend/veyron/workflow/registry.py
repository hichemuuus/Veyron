"""Workflow registry — persist and manage reusable workflows."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from sqlmodel import select, delete, update, func
from veyron.db.base import sync_session_scope
from veyron.db.models import Workflow as WorkflowDB, WorkflowStepModel
from veyron.workflow.models import (
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowStep,
)

logger = logging.getLogger(__name__)


def _step_to_model(workflow_pid: str, index: int, step: WorkflowStep) -> WorkflowStepModel:
    return WorkflowStepModel(
        workflow_public_id=workflow_pid,
        step_index=index,
        step_type=step.step_type,
        name=step.name,
        tool_name=step.tool_name,
        params_json=json.dumps(step.params),
        condition=step.condition,
        retry_count=step.retry_count,
        retry_delay_ms=step.retry_delay_ms,
        failure_policy=step.failure_policy,
    )


def _model_to_step(model: WorkflowStepModel) -> WorkflowStep:
    return WorkflowStep(
        step_type=model.step_type,
        name=model.name,
        tool_name=model.tool_name,
        params=json.loads(model.params_json) if model.params_json else {},
        condition=model.condition,
        retry_count=model.retry_count,
        retry_delay_ms=model.retry_delay_ms,
        failure_policy=model.failure_policy,
    )


class WorkflowRegistry:
    """Registry for reusable workflow definitions."""

    def save(self, definition: WorkflowDefinition) -> str:
        """Save a workflow definition. Returns public_id. Updates existing if name matches."""
        with sync_session_scope() as session:
            existing = session.exec(select(WorkflowDB).where(WorkflowDB.name == definition.name)).first()
            if existing:
                existing.description = definition.description
                existing.version = definition.version
                existing.tags = ",".join(definition.tags)
                existing.variable_names = json.dumps(definition.variables)
                existing.step_count = len(definition.steps)
                session.add(existing)
                # Delete old steps
                session.exec(delete(WorkflowStepModel).where(WorkflowStepModel.workflow_public_id == existing.public_id))
                # Save new steps
                for i, step in enumerate(definition.steps):
                    session.add(_step_to_model(existing.public_id, i, step))
                session.flush()
                return existing.public_id

            public_id = str(uuid4())
            wf = WorkflowDB(
                public_id=public_id,
                name=definition.name,
                description=definition.description,
                version=definition.version,
                tags=",".join(definition.tags),
                variable_names=json.dumps(definition.variables),
                step_count=len(definition.steps),
                use_count=0,
                source="manual",
                enabled=True,
            )
            session.add(wf)
            for i, step in enumerate(definition.steps):
                session.add(_step_to_model(public_id, i, step))
            session.flush()
            logger.info("saved workflow: %s (%s)", definition.name, public_id)
            return public_id

    def get(self, public_id: str) -> WorkflowDefinition | None:
        with sync_session_scope() as session:
            wf = session.exec(select(WorkflowDB).where(WorkflowDB.public_id == public_id)).first()
            if not wf:
                return None
            steps = session.exec(
                select(WorkflowStepModel)
                .where(WorkflowStepModel.workflow_public_id == public_id)
                .order_by(WorkflowStepModel.step_index)
            ).all()
            return WorkflowDefinition(
                name=wf.name,
                description=wf.description,
                version=wf.version,
                tags=wf.tags.split(",") if wf.tags else [],
                variables=json.loads(wf.variable_names) if wf.variable_names else [],
                steps=[_model_to_step(s) for s in steps],
            )

    def get_by_name(self, name: str) -> WorkflowDefinition | None:
        with sync_session_scope() as session:
            wf = session.exec(select(WorkflowDB).where(WorkflowDB.name == name)).first()
            if not wf:
                return None
            return self.get(wf.public_id)

    def list_workflows(self, enabled_only: bool = True, limit: int = 50, offset: int = 0) -> list[dict]:
        with sync_session_scope() as session:
            stmt = select(WorkflowDB)
            if enabled_only:
                stmt = stmt.where(WorkflowDB.enabled == True)
            wfs = session.exec(stmt.order_by(WorkflowDB.use_count.desc()).offset(offset).limit(limit)).all()
            return [{
                "public_id": w.public_id,
                "name": w.name,
                "description": w.description,
                "version": w.version,
                "tags": w.tags.split(",") if w.tags else [],
                "step_count": w.step_count,
                "use_count": w.use_count,
                "success_rate": w.success_rate,
                "source": w.source,
                "enabled": w.enabled,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            } for w in wfs]

    def record_execution(self, public_id: str, result: WorkflowExecutionResult) -> None:
        """Record an execution outcome for analytics."""
        with sync_session_scope() as session:
            wf = session.exec(select(WorkflowDB).where(WorkflowDB.public_id == public_id)).first()
            if wf:
                wf.use_count = (wf.use_count or 0) + 1
                total = wf.use_count
                success_count = (total * wf.success_rate) + (1 if result.success else 0)
                wf.success_rate = round(success_count / (total + 1), 4)
                session.add(wf)

    def delete(self, public_id: str) -> bool:
        with sync_session_scope() as session:
            wf = session.exec(select(WorkflowDB).where(WorkflowDB.public_id == public_id)).first()
            if not wf:
                return False
            session.exec(delete(WorkflowStepModel).where(WorkflowStepModel.workflow_public_id == public_id))
            session.delete(wf)
            return True

    def get_stats(self) -> dict:
        with sync_session_scope() as session:
            total = len(session.exec(select(WorkflowDB)).all())
            enabled = len(session.exec(select(WorkflowDB).where(WorkflowDB.enabled == True)).all())
            total_uses = sum(w.use_count or 0 for w in session.exec(select(WorkflowDB)).all())
            return {"total": total, "enabled": enabled, "total_uses": total_uses}


# Singleton
_registry: WorkflowRegistry | None = None


def get_workflow_registry() -> WorkflowRegistry:
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
    return _registry


def reset_workflow_registry() -> None:
    global _registry
    _registry = None
