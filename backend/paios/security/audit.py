"""Append-only audit log.

Every privileged action is written here as JSON, in addition to the AuditEvent
SQL table. The file log is tamper-evident in practice (append-only, newline
delimited) and survives DB resets.

See ARCHITECTURE.md §7.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from paios.config import DATA_DIR

logger = logging.getLogger(__name__)

AUDIT_DIR = DATA_DIR / "audit"
_lock = threading.Lock()


def _audit_file() -> Path:
    """One file per UTC day: audit-YYYY-MM-DD.jsonl."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return AUDIT_DIR / f"audit-{today}.jsonl"


def record(
    *,
    action: str,
    subject: str,
    permission: str,
    inputs: Optional[dict[str, Any]] = None,
    outcome: str = "pending",
    reason: Optional[str] = None,
    detail: Optional[str] = None,
) -> str:
    """Write one audit record. Returns the record id.

    Safe to call from sync code; uses a thread lock for file appends.
    """
    record_id = uuid4().hex
    entry = {
        "id": record_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "subject": subject,
        "permission": permission,
        "inputs": inputs or {},
        "outcome": outcome,
        "reason": reason,
        "detail": detail,
    }
    line = json.dumps(entry, default=str)
    try:
        with _lock:
            with open(_audit_file(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as e:
        logger.error("audit write failed: %s", e)
    return record_id


def read_recent(limit: int = 100) -> list[dict[str, Any]]:
    """Read the most recent N audit entries (newest first)."""
    files = sorted(AUDIT_DIR.glob("audit-*.jsonl"), reverse=True)
    out: list[dict[str, Any]] = []
    for f in files:
        if len(out) >= limit:
            break
        try:
            with open(f, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            if len(out) >= limit:
                break
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
