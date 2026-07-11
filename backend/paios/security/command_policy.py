"""Shell command policy.

Classifies a shell command into a permission level using a starter
allowlist/denylist. The Phase-2 command-safety micro-model will replace the
static classifier with a learned one (same interface).

See ARCHITECTURE.md §7 and DECISIONS.md (COMMAND POLICY STARTER).
"""

from __future__ import annotations

import re
import shlex
from enum import Enum
from typing import Optional


class PermissionLevel(str, Enum):
    """Tool/command permission levels."""

    FREE = "free"  # safe read-only; runs silently
    CONFIRM = "confirm"  # requires user approval
    RESTRICTED = "restricted"  # dangerous; approval + reason


# Read-only commands safe to run without confirmation.
_FREE_ALLOWLIST = {
    "ls", "dir", "cat", "type", "head", "tail", "wc", "file", "stat",
    "echo", "printf", "pwd", "whoami", "hostname", "date", "cal",
    "find", "tree", "du", "df",
    "grep", "rg", "ack", "fgrep", "egrep", "sort", "uniq", "cut", "tr",
    "which", "where", "whereis", "command",
    "git status", "git log", "git diff", "git branch", "git show", "git remote",
    "node --version", "npm --version", "python --version", "pip --version",
    "systeminfo", "tasklist", "wmic",
    "ps", "top", "free", "uname", "uptime", "lscpu", "lsblk",
}

# Commands that are always restricted, regardless of arguments.
_RESTRICTED_KEYWORDS = {
    "rm", "rmdir", "del", "erase", "rd",
    "format", "mkfs",
    "shutdown", "reboot", "halt", "poweroff",
    "dd", "shred",
    "reg", "regedit",
    "netsh", "sc", "chkdsk",
    "sudo", "su", "runas",
    "kill -9", "taskkill",
    "chmod -R", "chown -R", "attrib",
    "mv /", "cp /",
    ">:",
}

# Patterns that look destructive even on otherwise-allowed commands.
_DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf?\b"),
    re.compile(r"\bformat\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\b.*\bof="),
]


def _extract_head(command: str) -> str:
    """Best-effort extraction of the command head (first word(s)).

    Handles "git status" style multi-word commands and shell metacharacters.
    """
    command = command.strip()
    # Strip leading env-var assignments like FOO=bar cmd ...
    while re.match(r"^[A-Za-z_][A-Za-z0-9_]*=\S+\s+", command):
        command = command.split(None, 1)[1]
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return ""
    head = tokens[0]
    # Two-word allowlist entries (git status, etc.)
    if len(tokens) >= 2:
        two = f"{tokens[0]} {tokens[1]}"
        if two in _FREE_ALLOWLIST:
            return two
    return head


def classify_command(command: str) -> PermissionLevel:
    """Classify a shell command.

    Rules (in order):
      1. Empty or exceeds max length → FREE (nothing to run).
      2. Matches a destructive pattern or restricted keyword → RESTRICTED.
      3. Head (or two-word head) is in the allowlist AND no shell metachar
         that could smuggle a second command → FREE.
      4. Otherwise → CONFIRM.

    Note: shell metacharacters (;, |, &&, ||, >, <, `) in an allowlisted
    command drop it to CONFIRM at minimum, because they can chain a second
    command.
    """
    command = command.strip()
    if not command:
        return PermissionLevel.FREE

    # Reject overly long commands to prevent DoS.
    if len(command) > 4096:
        return PermissionLevel.RESTRICTED

    # Normalize whitespace: collapse runs of any whitespace (including tabs,
    # non-breaking spaces, etc.) into single spaces for matching.
    import re as _re
    normalized = _re.sub(r'\s+', ' ', command)
    low = normalized.lower()

    # 2. Restricted.
    for kw in _RESTRICTED_KEYWORDS:
        low_kw = kw.lower()
        if low == low_kw or low.startswith(low_kw + " ") or low.startswith(low_kw + "\t"):
            return PermissionLevel.RESTRICTED
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(low):
            return PermissionLevel.RESTRICTED

    # Shell-metachar detection: if present, never FREE.
    # Use raw command (not normalized) to catch whitespace-obfuscated metachars
    # but still detect them.
    has_metachar = bool(_re.search(r"[;|&<>`]|\$\(", low))

    head = _extract_head(normalized)
    head_low = head.lower()

    # 3. Allowlist + no metachar → FREE.
    if head_low in {c.lower() for c in _FREE_ALLOWLIST} and not has_metachar:
        return PermissionLevel.FREE

    # 4. Default → CONFIRM.
    return PermissionLevel.CONFIRM


def classify(command: str) -> PermissionLevel:
    """Alias for classify_command (used by the terminal tool)."""
    return classify_command(command)
