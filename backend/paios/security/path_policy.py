"""Filesystem path policy.

Validates every filesystem path the AI touches against the configured sandbox
roots. Rejects traversal, symlink escapes, and absolute paths outside roots.

See ARCHITECTURE.md §7.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from paios.config import get_settings


class PathPolicyError(PermissionError):
    """Raised when a path is outside the sandbox roots."""


def _load_roots() -> list[Path]:
    return [Path(root).resolve() for root in get_settings().security.sandbox_roots]


def _normalize_input(path: str | Path) -> Path:
    """Decode and normalize a user-supplied path string.

    Handles URL-encoded traversal attempts and ~ expansion.
    """
    if isinstance(path, str):
        path = unquote(path)
    p = Path(path).expanduser()
    return p


def is_within_roots(path: str | Path, roots: list[Path] | None = None) -> bool:
    """Return True if the resolved path is inside one of the roots.

    Symlinks are resolved (realpath) before the check, so a symlink pointing
    outside a root is rejected. Uses strict resolution where possible;
    falls back to non-strict for non-existent paths (still respects parent-level
    symlink resolution).
    """
    roots = roots or _load_roots()
    if not roots:
        return False
    try:
        normalized = _normalize_input(path)
        # Resolve strictly if path exists, otherwise resolve what we can.
        if normalized.exists():
            resolved = normalized.resolve(strict=True)
        else:
            # For non-existent paths, resolve the parent chain then append.
            parent = normalized.parent.resolve(strict=True) if normalized.parent.exists() else normalized.parent
            resolved = parent / normalized.name
    except (OSError, ValueError, RuntimeError) as e:
        raise PathPolicyError(f"cannot resolve path: {path!r}: {e}")
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def validate_path(path: str | Path, roots: list[Path] | None = None, must_exist: bool = False) -> Path:
    """Validate and return the resolved path, or raise PathPolicyError.

    Args:
        path: path to validate.
        roots: optional override for sandbox roots (testing).
        must_exist: if True, raise if the path doesn't exist on disk.

    Never returns a path outside the configured roots.
    """
    roots = roots or _load_roots()
    normalized = _normalize_input(path)
    if not is_within_roots(normalized, roots):
        raise PathPolicyError(
            f"path outside sandbox roots: {path!r}. Allowed roots: {[str(r) for r in roots]}"
        )
    resolved = normalized.resolve(strict=False)
    if must_exist and not resolved.exists():
        raise PathPolicyError(f"path does not exist: {resolved}")
    return resolved


def list_allowed_roots() -> list[str]:
    """Return the configured roots as strings (for display in the UI)."""
    return [str(r) for r in _load_roots()]
