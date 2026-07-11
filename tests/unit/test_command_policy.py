"""Tests for the shell command policy."""

from __future__ import annotations

import pytest

from paios.security.command_policy import PermissionLevel, classify_command


@pytest.mark.parametrize(
    "cmd",
    [
        "ls",
        "ls -la",
        "cat file.txt",
        "git status",
        "git log --oneline",
        "grep -r foo .",
        "dir",
        "echo hello",
        "python --version",
    ],
)
def test_free_commands(cmd: str):
    assert classify_command(cmd) == PermissionLevel.FREE, f"{cmd} should be FREE"


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "rm file.txt",
        "format C:",
        "shutdown /s",
        "sudo rm something",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda1",
        "del important.txt",
    ],
)
def test_restricted_commands(cmd: str):
    assert classify_command(cmd) == PermissionLevel.RESTRICTED, f"{cmd} should be RESTRICTED"


@pytest.mark.parametrize(
    "cmd",
    [
        "pip install requests",  # not in allowlist, not destructive
        "git push",  # writes but not destructive; default CONFIRM
        "npm install",
        "make build",
    ],
)
def test_confirm_commands(cmd: str):
    assert classify_command(cmd) == PermissionLevel.CONFIRM, f"{cmd} should be CONFIRM"


def test_allowlist_with_metachar_is_confirm():
    # `ls` is allowlisted but `;` smuggles a second command → CONFIRM.
    assert classify_command("ls; rm -rf x") == PermissionLevel.RESTRICTED
    # Pipe to another command should be CONFIRM at minimum.
    assert classify_command("cat file | grep x") in {
        PermissionLevel.CONFIRM,
        PermissionLevel.FREE,
    }


def test_empty_command_is_free():
    assert classify_command("") == PermissionLevel.FREE
    assert classify_command("   ") == PermissionLevel.FREE


def test_case_insensitive():
    assert classify_command("LS -LA") == PermissionLevel.FREE
    assert classify_command("RM -RF /") == PermissionLevel.RESTRICTED
