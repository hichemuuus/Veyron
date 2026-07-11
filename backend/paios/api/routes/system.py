"""System API routes.

  GET /api/system/overview  — snapshot of CPU/RAM/disk
  GET /api/system/cpu
  GET /api/system/memory
  GET /api/system/disk
  GET /api/system/health
"""

from __future__ import annotations

from fastapi import APIRouter

from paios.tools.system_monitor import SystemMonitorTool
from paios.tools.base import ToolContext

router = APIRouter(prefix="/api/system", tags=["system"])

_tool = SystemMonitorTool()


async def _run(op: str, **kwargs) -> dict:
    ctx = ToolContext(task_public_id="system")
    result = await _tool.run(ctx, operation=op, **kwargs)
    return {"ok": result.ok, "output": result.output, "data": result.data, "error": result.error}


@router.get("/overview")
async def overview() -> dict:
    return await _run("overview")


@router.get("/cpu")
async def cpu() -> dict:
    return await _run("cpu")


@router.get("/memory")
async def memory() -> dict:
    return await _run("memory")


@router.get("/disk")
async def disk() -> dict:
    return await _run("disk")


@router.get("/health")
async def health() -> dict:
    return await _run("health")
