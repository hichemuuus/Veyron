"""
Verify the Veyron development/build environment.

Checks:
- Python version (>=3.11, <3.14)
- Virtual environment activation
- All required dependencies are installed
- psutil platform compatibility

Usage:
    python scripts/verify_environment.py
"""

import importlib.metadata
import sys

REQUIRED_PACKAGES = {
    "fastapi": "FastAPI",
    "uvicorn": "uvicorn",
    "pydantic": "Pydantic",
    "pydantic_settings": "Pydantic-Settings",
    "sqlmodel": "SQLModel",
    "psutil": "psutil",
    "httpx": "httpx",
    "pyyaml": "PyYAML",
    "numpy": "NumPy",
}


def check() -> int:
    errors = 0

    # Python version
    version = sys.version_info[:2]
    min_v = (3, 11)
    max_v = (3, 14)
    if version < min_v:
        print(f"[FAIL] Python {version[0]}.{version[1]} < {min_v[0]}.{min_v[1]}")
        errors += 1
    elif version >= max_v:
        print(f"[FAIL] Python {version[0]}.{version[1]} >= {max_v[0]}.{max_v[1]} (not yet supported)")
        errors += 1
    else:
        print(f"[PASS] Python {version[0]}.{version[1]}")

    # Virtual environment
    if sys.prefix == sys.base_prefix:
        print("[WARN] Not running inside a virtual environment")
    else:
        print(f"[PASS] Virtual environment: {sys.prefix}")

    # Dependencies
    for module, pkg_name in REQUIRED_PACKAGES.items():
        try:
            dist = importlib.metadata.distribution(pkg_name)
            print(f"[PASS] {module} ({dist.version})")
        except importlib.metadata.PackageNotFoundError:
            print(f"[FAIL] {module} not installed")
            errors += 1

    # psutil CPU times platform check
    try:
        import psutil
        ct = psutil.cpu_times()
        print(f"[PASS] psutil.cpu_times() fields: {ct._fields}")
    except Exception as e:
        print(f"[FAIL] psutil.cpu_times() error: {e}")
        errors += 1

    if errors:
        bar = "=" * 60
        print(f"""
{bar}
  {errors} check(s) FAILED.
  Ensure you are running from the project virtual
  environment and have installed all dependencies:
    python -m pip install -r backend/requirements.txt
{bar}""")
    else:
        print("\nAll checks passed. Environment is ready.")

    return errors


if __name__ == "__main__":
    sys.exit(check())
