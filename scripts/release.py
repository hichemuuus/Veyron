"""
Veyron release orchestrator.

Performs a dry-run or live release by automating version bumps, builds,
signing, and GitHub release creation.

Usage:
    # Dry run (shows what would happen)
    python scripts/release.py --dry-run --patch

    # Live release (publishes to GitHub)
    python scripts/release.py --patch              # bump patch: 1.0.0 -> 1.0.1
    python scripts/release.py --minor              # bump minor: 1.0.0 -> 1.1.0
    python scripts/release.py --major              # bump major: 1.0.0 -> 2.0.0
    python scripts/release.py --version 1.2.3      # explicit version
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VERSION_FILES: dict[str, str] = {
    "backend/veyron/__init__.py": r'__version__\s*=\s*["\']([^"\']+)["\']',
    "frontend/src-tauri/tauri.conf.json": r'"version":\s*"([^"]+)"',
    "frontend/src-tauri/Cargo.toml": r'version\s*=\s*"([^"]+)"',
}


def current_version() -> str:
    init = PROJECT_ROOT / "backend/veyron/__init__.py"
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init.read_text())
    return m.group(1) if m else "0.0.0"


def bump_version(ver: str, segment: str) -> str:
    parts = [int(x) for x in ver.split(".")]
    if segment == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    elif segment == "minor":
        parts[1] += 1
        parts[2] = 0
    elif segment == "patch":
        parts[2] += 1
    return ".".join(str(p) for p in parts)


def update_version_in_file(filepath: Path, pattern: str, new_ver: str) -> bool:
    text = filepath.read_text(encoding="utf-8")
    new_text = re.sub(pattern, lambda m: m.group(0).replace(m.group(1), new_ver), text)
    if text == new_text:
        return False
    filepath.write_text(new_text, encoding="utf-8")
    return True


def update_versions(new_ver: str, dry_run: bool = False) -> bool:
    """Update version in all tracked files. Returns True if any changed."""
    any_changed = False
    for rel, pattern in VERSION_FILES.items():
        fp = PROJECT_ROOT / rel
        if not fp.exists():
            print(f"  SKIP  {rel} (not found)")
            continue
        if dry_run:
            print(f"  WOULD UPDATE {rel} -> {new_ver}")
            any_changed = True
        elif update_version_in_file(fp, pattern, new_ver):
            print(f"  UPDATED {rel} -> {new_ver}")
            any_changed = True
        else:
            print(f"  OK     {rel} already at {new_ver}")
    return any_changed


def git_commit_and_tag(ver: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  DRY-RUN: git add -A && git commit -m 'chore: bump to v{ver}' && git tag v{ver}")
        return
    subprocess.run(["git", "add", "-A"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"chore: bump to v{ver}"],
        cwd=PROJECT_ROOT, check=True,
    )
    subprocess.run(["git", "tag", f"v{ver}"], cwd=PROJECT_ROOT, check=True)
    print(f"  Committed and tagged v{ver}")


def build_sidecar(dry_run: bool) -> None:
    if dry_run:
        print("  DRY-RUN: python scripts/build_backend.py")
        return
    subprocess.run(
        [sys.executable, "scripts/build_backend.py"],
        cwd=PROJECT_ROOT, check=True,
    )
    print("  Sidecar built")


def build_frontend(dry_run: bool) -> None:
    if dry_run:
        print("  DRY-RUN: cd frontend && npm run build")
        return
    subprocess.run(["npm", "run", "build"], cwd=PROJECT_ROOT / "frontend", check=True)
    print("  Frontend built")


def build_tauri(dry_run: bool) -> None:
    if dry_run:
        print("  DRY-RUN: cd frontend && npm run tauri:build")
        return
    subprocess.run(
        ["npm", "run", "tauri:build"],
        cwd=PROJECT_ROOT / "frontend", check=True,
    )
    print("  Tauri app built")


def sign_and_manifest(ver: str, dry_run: bool) -> None:
    nsis_dir = PROJECT_ROOT / "frontend" / "src-tauri" / "target" / "release" / "bundle" / "nsis"
    candidates = list(nsis_dir.glob("Veyron_*.exe"))
    if not candidates:
        print("  WARNING: no installer found to sign")
        return
    installer = candidates[0]
    if dry_run:
        print(f"  DRY-RUN: python scripts/sign_update.py sign {installer} --version {ver}")
        return
    subprocess.run(
        [sys.executable, "scripts/sign_update.py", "sign", str(installer), "--version", ver],
        cwd=PROJECT_ROOT, check=True,
    )
    print(f"  Installer signed: {installer.name}")


def push_to_github(dry_run: bool) -> None:
    if dry_run:
        print("  DRY-RUN: git push origin main && git push origin v{ver}")
        return
    subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True)
    print("  Pushed main")
    ver = current_version()
    subprocess.run(
        ["git", "push", "origin", f"v{ver}"],
        cwd=PROJECT_ROOT, check=True,
    )
    print(f"  Pushed tag v{ver}")


def validate_release(ver: str, dry_run: bool) -> None:
    """Run pre-release validation checks."""
    print(f"\nValidating v{ver} ...")

    # Check version consistency
    errors = []
    for rel, pattern in VERSION_FILES.items():
        fp = PROJECT_ROOT / rel
        if fp.exists():
            m = re.search(pattern, fp.read_text())
            found = m.group(1) if m else None
            if found != ver:
                errors.append(f"  {rel}: expected {ver}, found {found}")

    # Check signing key
    pubkey = PROJECT_ROOT / "veyron-updater-key.private.pub"
    pubkey_parent = PROJECT_ROOT.parent / "veyron-updater-key.private.pub"
    if not pubkey.exists() and not pubkey_parent.exists():
        errors.append("  Public signing key not found (veyron-updater-key.private.pub)")

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(e)
        if not dry_run:
            sys.exit(1)
        else:
            print("  (dry-run: ignoring validation errors)")
    else:
        print("  All checks passed.")


def main():
    parser = argparse.ArgumentParser(description="Veyron release orchestrator")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--patch", action="store_true", help="bump patch version")
    group.add_argument("--minor", action="store_true", help="bump minor version")
    group.add_argument("--major", action="store_true", help="bump major version")
    group.add_argument("--version", type=str, help="explicit version (e.g. 1.2.3)")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen")
    parser.add_argument("--push", action="store_true", help="push to GitHub after build")
    args = parser.parse_args()

    cur = current_version()
    print(f"Current version: {cur}")

    if args.version:
        new_ver = args.version.lstrip("v")
    elif any([args.patch, args.minor, args.major]):
        segment = "patch" if args.patch else "minor" if args.minor else "major"
        new_ver = bump_version(cur, segment)
    else:
        print("No version bump specified. Use --patch, --minor, --major, or --version")
        sys.exit(1)

    print(f"Target version:  {new_ver}")
    if args.dry_run:
        print("\n-- DRY RUN --")

    print("\n1. Validating...")
    validate_release(new_ver, args.dry_run)

    print("\n2. Updating version files...")
    changed = update_versions(new_ver, dry_run=args.dry_run)
    if not args.dry_run and not changed and cur != new_ver:
        print("  ERROR: version files not updated. Check patterns.")
        sys.exit(1)

    print("\n3. Committing and tagging...")
    git_commit_and_tag(new_ver, args.dry_run)

    print("\n4. Building sidecar...")
    build_sidecar(args.dry_run)

    print("\n5. Building frontend...")
    build_frontend(args.dry_run)

    print("\n6. Building Tauri app...")
    build_tauri(args.dry_run)

    print("\n7. Signing installer + generating latest.json...")
    sign_and_manifest(new_ver, args.dry_run)

    if args.push:
        print("\n8. Pushing to GitHub (triggers CI/CD)...")
        push_to_github(args.dry_run)
    else:
        print("\n8. SKIP push (use --push to push to GitHub)")
        print("   Push the tag manually to trigger CI/CD:")
        print(f"     git push origin main")
        print(f"     git push origin v{new_ver}")

    print(f"\nDone. Release v{new_ver} prepared.")


if __name__ == "__main__":
    main()
