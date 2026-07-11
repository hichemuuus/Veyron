"""Terminal tool (sandboxed, permission-controlled).

Runs shell commands. Every command is classified by the command policy:
  FREE       → runs silently (read-only commands)
  CONFIRM    → requires user approval via the confirmation flow
  RESTRICTED → requires approval + a reason; destructive commands

No uncontrolled shell execution. See ARCHITECTURE.md §7.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from typing import Any, ClassVar, Type

from pydantic import BaseModel, Field

from paios.db.base import sync_session_scope
from paios.db.models import ToolInvocation
from paios.security.audit import record as audit_record
from paios.security.command_policy import PermissionLevel, classify_command
from paios.tools.base import Tool, ToolContext, ToolResult


class TerminalInputs(BaseModel):
    command: str = Field(..., description="The shell command to run.")
    cwd: str | None = Field(default=None, description="Working directory (inside sandbox roots).")
    timeout: int = Field(
        default=30, description="Max seconds the command may run before being killed.", ge=1, le=300
    )


class TerminalTool(Tool):
    name: ClassVar[str] = "terminal"
    description: ClassVar[str] = (
        "Run a shell command. Read-only commands (ls, cat, git status) run freely; "
        "other commands require confirmation; destructive commands require approval + reason. "
        "Prefer the more specific filesystem_read and system_monitor tools when possible."
    )
    # The tool itself is CONFIRM; per-command classification may downgrade to FREE
    # or escalate to RESTRICTED at run time.
    permission: ClassVar[PermissionLevel] = PermissionLevel.CONFIRM
    Inputs: ClassVar[Type[BaseModel]] = TerminalInputs

    async def run(self, ctx: ToolContext, **inputs: Any) -> ToolResult:
        command = inputs["command"].strip()
        cwd = inputs.get("cwd")
        timeout = inputs.get("timeout", 30)

        if not command:
            return ToolResult(ok=False, error="empty command")

        # Classify per-command; the effective permission may differ from class default.
        level = classify_command(command)

        # If CONFIRM or RESTRICTED, gate via the confirmation flow.
        if level != PermissionLevel.FREE:
            approved, reason = await self._confirm(ctx, command, level)
            if not approved:
                msg = f"command not approved: {command}"
                self._log(ctx, command, level, ToolResult(ok=False, error=msg), approved=False)
                return ToolResult(ok=False, error=msg)

        # Run it.
        result = await self._execute(command, cwd, timeout)
        self._log(ctx, command, level, result, approved=True, reason=reason if level != PermissionLevel.FREE else None)
        return result

    async def _confirm(
        self, ctx: ToolContext, command: str, level: PermissionLevel
    ) -> tuple[bool, str | None]:
        """Ask the user (via the confirmation flow) to approve the command."""
        if ctx.confirm is not None:
            # Test/programmatic injection.
            return await ctx.confirm(
                topic=ctx.task_public_id,
                tool_name=self.name,
                permission=level,
                summary=f"Run: {command}",
                inputs={"command": command},
            )
        # Default: real confirmation manager.
        from paios.security.confirmations import get_manager
        from paios.config import get_settings

        manager = get_manager()
        return await manager.request(
            topic=ctx.task_public_id,
            tool_name=self.name,
            permission=level,
            summary=f"Run: {command}",
            inputs={"command": command},
            timeout=float(get_settings().security.confirm_timeout_seconds),
        )

    async def _execute(self, command: str, cwd: str | None, timeout: int) -> ToolResult:
        """Run the command in a subprocess and capture output."""
        # Use a shell so pipes & builtins work; policy has already gated this.
        # On Windows we use cmd.exe; elsewhere /bin/sh.
        is_windows = sys.platform.startswith("win")
        shell_args = ["cmd.exe", "/c", command] if is_windows else ["/bin/sh", "-c", command]

        env = dict(os.environ)
        # Remove potentially sensitive environment variables.
        for sensitive_key in ("API_KEY", "API_SECRET", "ACCESS_KEY", "SECRET_KEY",
                              "TOKEN", "PASSWORD", "PASS", "SECRET", "PRIVATE_KEY",
                              "AUTH_TOKEN", "AWS_SECRET_ACCESS_KEY"):
            env.pop(sensitive_key, None)
            env.pop(sensitive_key.lower(), None)
            env.pop(sensitive_key.upper(), None)
        try:
            cwd_path = cwd if cwd else None
            proc = await asyncio.create_subprocess_exec(
                *shell_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd_path,
                env=env,
            )
        except (OSError, FileNotFoundError) as e:
            return ToolResult(ok=False, error=f"failed to start: {e}")

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return ToolResult(ok=False, error=f"timed out after {timeout}s", data={"command": command})

        stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        rc = proc.returncode if proc.returncode is not None else -1

        # Combine: prefer stdout; include stderr only if non-empty.
        parts = []
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append(f"[stderr]\n{stderr.rstrip()}")
        text = "\n".join(parts) or "(no output)"
        if rc != 0:
            text = f"{text}\n[exit code {rc}]"

        ok = rc == 0
        return ToolResult(
            output=text,
            data={"command": command, "exit_code": rc, "stdout_len": len(stdout), "stderr_len": len(stderr)},
            ok=ok,
            error=None if ok else f"exit code {rc}",
        )

    def _log(
        self,
        ctx: ToolContext,
        command: str,
        level: PermissionLevel,
        result: ToolResult,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> None:
        audit_record(
            action="tool.invoke.terminal",
            subject=ctx.task_public_id,
            permission=level.value,
            inputs={"command": command},
            outcome=("success" if result.ok else "error") if approved else "denied",
            reason=reason,
            detail=result.error,
        )
        try:
            with sync_session_scope() as session:
                session.add(
                    ToolInvocation(
                        task_public_id=ctx.task_public_id,
                        tool_name=self.name,
                        permission=level.value,
                        inputs=json.dumps({"command": command}),
                        result=str(result.data),
                        ok=result.ok,
                        duration_ms=result.duration_ms,
                        error=result.error,
                    )
                )
        except Exception:
            pass
