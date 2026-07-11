"""Filesystem read tool.

Reads files and lists directories inside the configured sandbox roots. Path
policy validates every path. Write operations are a separate tool (Phase 2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal, Type

from pydantic import BaseModel, Field

from paios.db.base import sync_session_scope
from paios.db.models import ToolInvocation
from paios.security.command_policy import PermissionLevel
from paios.security.path_policy import PathPolicyError, validate_path
from paios.tools.base import Tool, ToolContext, ToolResult


class FilesystemReadInputs(BaseModel):
    operation: Literal["read_file", "list_dir", "stat"] = Field(
        ..., description="read_file: get file contents; list_dir: list a directory; stat: file metadata."
    )
    path: str = Field(..., description="Absolute or ~ path within the sandbox roots.")
    max_bytes: int = Field(
        default=65536, description="Max bytes to read from a file (read_file only).", ge=1, le=1_048_576
    )


class FilesystemReadTool(Tool):
    name: ClassVar[str] = "filesystem_read"
    description: ClassVar[str] = (
        "Read files and list directories inside the sandbox. "
        "Use for inspecting source code, configs, project structure, etc. "
        "Cannot write or delete."
    )
    permission: ClassVar[PermissionLevel] = PermissionLevel.FREE
    Inputs: ClassVar[Type[BaseModel]] = FilesystemReadInputs

    async def run(self, ctx: ToolContext, **inputs: Any) -> ToolResult:
        op = inputs["operation"]
        path_str = inputs["path"]
        max_bytes = inputs.get("max_bytes", 65536)

        try:
            path = validate_path(path_str)
        except PathPolicyError as e:
            return ToolResult(ok=False, error=str(e))

        if op == "read_file":
            return await self._read_file(ctx, path, max_bytes, path_str)
        elif op == "list_dir":
            return await self._list_dir(ctx, path, path_str)
        elif op == "stat":
            return await self._stat(ctx, path, path_str)
        return ToolResult(ok=False, error=f"unknown operation: {op}")

    async def _read_file(self, ctx: ToolContext, path: Path, max_bytes: int, original: str) -> ToolResult:
        if not path.exists():
            return self._fail(ctx, original, f"not found: {path}")
        if path.is_dir():
            return self._fail(ctx, original, f"is a directory, not a file: {path}")
        try:
            # Try text; fall back to a binary-safe message.
            data = path.read_bytes()[:max_bytes]
            try:
                text = data.decode("utf-8")
                output = text
            except UnicodeDecodeError:
                output = f"[binary file, {len(data)} bytes, not displayed]"
        except OSError as e:
            return self._fail(ctx, original, f"read error: {e}")
        result = ToolResult(
            output=output,
            data={"path": str(path), "bytes": len(data), "truncated": path.stat().st_size > len(data)},
        )
        self._log(ctx, result)
        return result

    async def _list_dir(self, ctx: ToolContext, path: Path, original: str) -> ToolResult:
        if not path.exists():
            return self._fail(ctx, original, f"not found: {path}")
        if not path.is_dir():
            return self._fail(ctx, original, f"is a file, not a directory: {path}")
        try:
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    size = child.stat().st_size if child.is_file() else None
                except OSError:
                    size = None
                entries.append(
                    {"name": child.name, "type": "dir" if child.is_dir() else "file", "size": size}
                )
        except OSError as e:
            return self._fail(ctx, original, f"list error: {e}")
        # Text representation for the LLM.
        lines = []
        for e in entries:
            if e["type"] == "dir":
                lines.append(f"  {e['name']}/")
            else:
                sz = e["size"] or 0
                lines.append(f"  {e['name']}  ({sz} bytes)")
        result = ToolResult(output="\n".join(lines) or "(empty)", data={"path": str(path), "entries": entries})
        self._log(ctx, result)
        return result

    async def _stat(self, ctx: ToolContext, path: Path, original: str) -> ToolResult:
        if not path.exists():
            return self._fail(ctx, original, f"not found: {path}")
        st = path.stat()
        info = {
            "path": str(path),
            "size": st.st_size,
            "is_dir": path.is_dir(),
            "is_file": path.is_file(),
            "mtime": st.st_mtime,
        }
        result = ToolResult(output=str(info), data=info)
        self._log(ctx, result)
        return result

    def _fail(self, ctx: ToolContext, original: str, error: str) -> ToolResult:
        result = ToolResult(ok=False, error=error)
        self._log(ctx, result)
        return result

    def _log(self, ctx: ToolContext, result: ToolResult) -> None:
        """Persist a ToolInvocation row."""
        import json

        try:
            with sync_session_scope() as session:
                session.add(
                    ToolInvocation(
                        task_public_id=ctx.task_public_id,
                        tool_name=self.name,
                        permission=self.permission.value,
                        inputs=json.dumps({"path": result.data.get("path", "")}),
                        result=str(result.data),
                        ok=result.ok,
                        duration_ms=result.duration_ms,
                        error=result.error,
                    )
                )
        except Exception:
            # Logging must never break the tool.
            pass
