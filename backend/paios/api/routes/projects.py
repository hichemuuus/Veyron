"""Project analysis API routes.

  POST /api/projects/analyze  — analyze a project directory
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paios.security.path_policy import PathPolicyError, validate_path
from paios.tools.project_analyzer import analyze_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


class AnalyzeRequest(BaseModel):
    path: str = Field(..., description="Project root directory path within sandbox.")
    max_depth: int = Field(default=5, ge=1, le=20)
    include_hidden: bool = Field(default=False)


@router.post("/analyze")
async def analyze(req: AnalyzeRequest) -> dict[str, Any]:
    """Analyze a project directory and return structured results."""
    try:
        root = validate_path(req.path)
    except PathPolicyError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not root.exists():
        raise HTTPException(status_code=404, detail=f"path not found: {root}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {root}")

    try:
        analysis = analyze_project(
            root=root,
            max_depth=req.max_depth,
            include_hidden=req.include_hidden,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"analysis failed: {e}")

    return {
        "root": analysis.root,
        "summary": analysis.summary,
        "file_count": analysis.file_count,
        "total_size_bytes": analysis.total_size_bytes,
        "technologies": analysis.technologies,
        "issues": analysis.issues,
        "recommendations": analysis.recommendations,
        "dependencies": analysis.dependencies,
        "structure": analysis.structure,
    }
