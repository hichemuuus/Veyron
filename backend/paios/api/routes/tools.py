"""Tools API routes.

  GET  /api/tools          — list all tools
  GET  /api/tools/{name}   — one tool's schema
  GET  /api/tools/{name}/recent  — recent invocations of a tool
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from paios.db.base import sync_session_scope
from paios.db.models import ToolInvocation
from paios.tools.registry import get_registry

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
def list_tools() -> dict[str, Any]:
    schemas = get_registry().schemas_for()
    return {"tools": schemas, "count": len(schemas)}


@router.get("/{name}")
def get_tool(name: str) -> dict[str, Any]:
    tool = get_registry().get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
    return type(tool).schema_for_llm()


@router.get("/{name}/recent")
def recent_invocations(name: str, limit: int = 20) -> dict[str, Any]:
    with sync_session_scope() as session:
        stmt = (
            select(ToolInvocation)
            .where(ToolInvocation.tool_name == name)
            .order_by(ToolInvocation.timestamp.desc())
            .limit(limit)
        )
        rows = session.exec(stmt).all()
        return {
            "tool": name,
            "invocations": [
                {
                    "timestamp": r.timestamp,
                    "task_public_id": r.task_public_id,
                    "permission": r.permission,
                    "inputs": json.loads(r.inputs) if r.inputs else {},
                    "ok": r.ok,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                }
                for r in rows
            ],
        }
