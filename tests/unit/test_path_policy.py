"""Tests for the filesystem path policy.

Covers: traversal attempts, absolute escapes, symlink escapes, valid paths.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from paios.security.path_policy import PathPolicyError, is_within_roots, validate_path


def test_valid_path_inside_root(sandbox_root: Path):
    target = sandbox_root / "file.txt"
    target.write_text("hi")
    resolved = validate_path(str(target))
    assert resolved.exists()
    assert resolved == target.resolve()


def test_valid_subdirectory(sandbox_root: Path):
    sub = sandbox_root / "a" / "b"
    sub.mkdir(parents=True)
    resolved = validate_path(str(sub))
    assert resolved == sub.resolve()


def test_traversal_blocked(sandbox_root: Path):
    # sandbox_root/../escape must be rejected even if it resolves somewhere.
    escape = str(sandbox_root.parent / "outside.txt")
    with pytest.raises(PathPolicyError):
        validate_path(escape)


def test_absolute_outside_root_blocked(sandbox_root: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    # Outside the sandbox root.
    with pytest.raises(PathPolicyError):
        validate_path(str(outside))


def test_url_encoded_traversal_blocked(sandbox_root: Path):
    # URL-encoded ../ should be decoded then rejected.
    encoded = str(sandbox_root) + "%2F..%2Fescape"
    with pytest.raises(PathPolicyError):
        validate_path(encoded)


def test_is_within_roots_true(sandbox_root: Path):
    assert is_within_roots(str(sandbox_root / "anything"))


def test_is_within_roots_false(tmp_path: Path, sandbox_root: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    assert not is_within_roots(str(outside))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need admin on Windows")
def test_symlink_escape_blocked(sandbox_root: Path, tmp_path: Path):
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("secret")
    link = sandbox_root / "link"
    link.symlink_to(outside)
    with pytest.raises(PathPolicyError):
        validate_path(str(link))


def test_must_exist(sandbox_root: Path):
    with pytest.raises(PathPolicyError):
        validate_path(str(sandbox_root / "does_not_exist"), must_exist=True)


def test_user_expansion_in_root(sandbox_root: Path):
    # ~ in the path should expand. Tilde path may or may not be in root, so we
    # just verify it doesn't raise a decoding error.
    try:
        validate_path("~/some_file")
    except PathPolicyError:
        pass  # expected — home likely outside sandbox_root
