"""Generate Tauri updater signing keys and sign update artifacts.

Usage:
    python scripts/sign_update.py generate-key                     # Generate a new key pair
    python scripts/sign_update.py sign <file> [--version X.Y.Z]   # Sign a file + generate latest.json
    python scripts/sign_update.py verify <file>                   # Verify a file signature
"""

import json
import os
import sys
import subprocess
import tempfile
from pathlib import Path


def generate_key():
    """Generate a new Tauri updater signing key pair."""
    print("Generating Tauri updater signing key...")
    result = subprocess.run(
        ["npx", "tauri", "signer", "generate", "--help"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and "tauri signer generate" in result.stdout:
        subprocess.run(
            ["npx", "tauri", "signer", "generate", "-w", "veyron-updater-key.private",
             "-p", "veyron-updater-key.private.pub"],
            check=True
        )
    else:
        # Fallback: generate using openssl
        print("Falling back to openssl key generation...")
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
             "-out", "veyron-updater-key.private"],
            check=True
        )
        subprocess.run(
            ["openssl", "rsa", "-pubout", "-in", "veyron-updater-key.private",
             "-out", "veyron-updater-key.private.pub"],
            check=True
        )

    print("Keys generated:")
    print(f"  Private: {Path('veyron-updater-key.private').absolute()}")
    print(f"  Public:  {Path('veyron-updater-key.private.pub').absolute()}")
    print()
    print("To get the public key in base64 format for tauri.conf.json:")
    print("  cat veyron-updater-key.private.pub | base64 -w0")
    print()
    print("IMPORTANT: Store the private key securely!")
    print("Add these secrets to GitHub Actions:")
    print("  - UPDATER_PRIVATE_KEY: contents of veyron-updater-key.private")
    print("  - UPDATER_PASSPHRASE: (optional) passphrase for the key")


def _resolve_key() -> tuple[Path, bool]:
    """Return (key_path, was_written) — writes key from env var if needed."""
    key_path = Path("veyron-updater-key.private")
    if key_path.exists():
        return key_path, False

    for env_var in ("UPDATER_PRIVATE_KEY", "TAURI_SIGNING_PRIVATE_KEY"):
        val = os.environ.get(env_var)
        if val:
            key_path.write_text(val)
            print(f"Key written from ${env_var}")
            return key_path, True

    print("Error: signing key not found.")
    print("  Place veyron-updater-key.private in the current directory, or")
    print("  set UPDATER_PRIVATE_KEY or TAURI_SIGNING_PRIVATE_KEY env var.")
    sys.exit(1)


def sign_file(file_path: str, version: str | None = None):
    """Sign a file with the Tauri updater private key.

    Args:
        file_path: Path to the file to sign (e.g. the NSIS installer).
        version: SemVer string. If omitted, extracted from *file_path*
            or falls back to reading ``backend/veyron/__init__.py``.
    """
    key_path, key_written = _resolve_key()

    file_path = Path(file_path)
    if not file_path.exists():
        print(f"Error: {file_path} not found")
        sys.exit(1)

    # Resolve version
    if version is None:
        # Try to extract from filename like Veyron_1.0.0_x64-setup.exe
        import re
        m = re.search(r"_(\d+\.\d+\.\d+)_", file_path.name)
        if m:
            version = m.group(1)
            print(f"Version extracted from filename: {version}")
        else:
            # Fallback: read from __init__.py
            init_py = Path(__file__).resolve().parent.parent / "backend" / "veyron" / "__init__.py"
            if init_py.exists():
                for line in init_py.read_text().splitlines():
                    if line.startswith("__version__"):
                        version = line.split('"')[1] if '"' in line else line.split("=")[1].strip().strip("'")
                        print(f"Version from __init__.py: {version}")
                        break
            if not version:
                version = "0.0.0"
                print("WARNING: could not determine version, using 0.0.0")

    print(f"Signing {file_path} (v{version})...")
    result = subprocess.run(
        ["npx", "tauri", "signer", "sign",
         "--private-key", str(key_path),
         "--file", str(file_path)],
        capture_output=True, text=True, check=True
    )
    signature = result.stdout.strip()

    # Save signature
    sig_path = file_path.with_suffix(file_path.suffix + ".sig")
    sig_path.write_text(signature)
    print(f"Signature saved to {sig_path}")
    print(f"Signature: {signature[:80]}...")

    # Generate update JSON
    json_path = file_path.parent / "latest.json"
    update_json = {
        "version": version,
        "notes": "See release notes for details.",
        "pub_date": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {
            "windows-x86_64": {
                "signature": signature,
                "url": f"https://github.com/hichemuuus/Veyron/releases/latest/download/{file_path.name}"
            }
        }
    }
    json_path.write_text(json.dumps(update_json, indent=2))
    print(f"Update manifest written to {json_path}")

    if key_written:
        key_path.unlink()
        print("Cleaned up temporary key file")


def verify_file(file_path: str):
    """Verify a file signature."""
    sig_path = Path(file_path + ".sig")
    if not sig_path.exists():
        print(f"Error: signature file {sig_path} not found")
        sys.exit(1)

    key_path = Path("veyron-updater-key.private.pub")
    if not key_path.exists():
        print("Error: Public key not found")
        sys.exit(1)

    result = subprocess.run(
        ["npx", "tauri", "signer", "verify",
         "--public-key", str(key_path),
         "--file", str(Path(file_path))],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print("Verification FAILED")
        print(result.stderr)
        sys.exit(1)
    print("Verification PASSED")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "generate-key":
        generate_key()
    elif command == "sign":
        if len(sys.argv) < 3:
            print("Usage: python scripts/sign_update.py sign <file> [--version X.Y.Z]")
            sys.exit(1)
        file_path = sys.argv[2]
        version = None
        if "--version" in sys.argv:
            idx = sys.argv.index("--version")
            if idx + 1 < len(sys.argv):
                version = sys.argv[idx + 1]
        sign_file(file_path, version=version)
    elif command == "verify":
        if len(sys.argv) < 3:
            print("Usage: python scripts/sign_update.py verify <file>")
            sys.exit(1)
        verify_file(sys.argv[2])
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)
