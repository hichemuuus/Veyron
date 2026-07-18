"""
Build Veyron Python backend as a standalone executable (sidecar) for Tauri.

Usage:
    python scripts/build_backend.py

Requires:
    pip install pyinstaller

Output:
    frontend/src-tauri/binaries/veyron-backend.exe   (Windows)
    frontend/src-tauri/binaries/veyron-backend-x86_64-pc-windows-msvc.exe  (with target triple)
"""

import os
import sys
import shutil
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
BINARIES_DIR = os.path.join(PROJECT_ROOT, "frontend", "src-tauri", "binaries")

SIDECAR_NAME = "veyron-backend"

# Tauri expects sidecar binaries with the Rust target triple suffix on Windows
TARGET_TRIPLE = "x86_64-pc-windows-msvc"
SIDECAR_OUT = f"{SIDECAR_NAME}-{TARGET_TRIPLE}.exe"

# Minimum Python version required by the project
MIN_PYTHON = (3, 11)
MAX_PYTHON = (3, 14)  # exclusive — Python >=3.14 is not yet supported


def _check_environment() -> None:
    """Validate Python version, virtual environment, and critical deps."""
    version = sys.version_info[:2]

    if version < MIN_PYTHON:
        print(f"ERROR: Python {version[0]}.{version[1]} is too old. "
              f"Need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}.")
        sys.exit(1)
    if version >= MAX_PYTHON:
        print(f"ERROR: Python {version[0]}.{version[1]} is not supported. "
              f"Need < {MAX_PYTHON[0]}.{MAX_PYTHON[1]}.")
        sys.exit(1)

    # Virtual environment check
    if sys.prefix == sys.base_prefix:
        print("WARNING: not running inside a virtual environment. "
              "The build may use the wrong Python version or missing deps.")

    # Dependency checks
    missing = []
    try:
        import psutil  # noqa: F401
    except ImportError:
        missing.append("psutil")

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        missing.append("PyInstaller")

    if missing:
        print(f"ERROR: missing required packages: {', '.join(missing)}")
        print("Install them with: python -m pip install " + " ".join(missing))
        sys.exit(1)

    print(f"Environment OK: Python {version[0]}.{version[1]} "
          f"({'venv' if sys.prefix != sys.base_prefix else 'system'})")


def build_sidecar():
    _check_environment()
    os.makedirs(BINARIES_DIR, exist_ok=True)

    HIDDEN_IMPORTS = [
        # FastAPI / Uvicorn
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        # Pydantic
        "pydantic", "pydantic_settings", "pydantic.fields",
        "pydantic.generics", "pydantic.dataclasses",
        # SQLAlchemy / SQLModel
        "sqlalchemy", "sqlalchemy.sql.default_comparator",
        "sqlalchemy.sql.type_api", "sqlalchemy.dialects.sqlite",
        "sqlmodel", "aiosqlite",
        # YAML
        "yaml", "_yaml",
        # HTTP
        "httpx", "httpcore", "h11", "sniffio",
        # System
        "psutil",
        # ML / sklearn
        "sklearn", "sklearn.feature_extraction.text",
        "sklearn.linear_model", "sklearn.pipeline",
        "sklearn.metrics.pairwise", "sklearn.dummy",
        "sklearn.multiclass", "sklearn.preprocessing",
        "sklearn.ensemble", "sklearn.tree", "sklearn.neighbors",
        "sklearn.svm", "sklearn.cluster", "sklearn.decomposition",
        # Numerical
        "numpy", "scipy", "scipy.sparse", "scipy.special",
        # Multipart
        "multipart", "python_multipart",
        # MLflow
        "mlflow", "mlflow.models", "mlflow.pyfunc",
        # Cloudpickle (mlflow dependency)
        "cloudpickle",
        # Dateutil (pandas dependency)
        "dateutil", "dateutil.parser", "dateutil.tz",
    ]

    print(f"Building {SIDECAR_NAME} with PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", SIDECAR_NAME,
        "--distpath", BINARIES_DIR,
        "--workpath", os.path.join(SCRIPTS_DIR, "build", "pyi_work"),
        "--specpath", os.path.join(SCRIPTS_DIR, "build"),
    ]
    for hi in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", hi])
    cmd.extend([
        "--add-data", f"{BACKEND_DIR}/veyron{os.pathsep}veyron",
        os.path.join(BACKEND_DIR, "veyron", "main.py"),
    ])

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)

    if result.returncode != 0:
        print("PyInstaller failed:")
        print(result.stderr)
        sys.exit(1)

    print(result.stdout)

    # Rename with target triple suffix
    src = os.path.join(BINARIES_DIR, f"{SIDECAR_NAME}.exe")
    dst = os.path.join(BINARIES_DIR, SIDECAR_OUT)

    if os.path.exists(src):
        if os.path.exists(dst):
            os.remove(dst)
        shutil.move(src, dst)
        print(f"Sidecar ready: {dst}")
    else:
        print(f"ERROR: {src} not found!")
        sys.exit(1)

    # Clean up build artifacts
    build_dir = os.path.join(SCRIPTS_DIR, "build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)

    print("Done. Run 'npm run tauri:build' to build the desktop application.")


if __name__ == "__main__":
    build_sidecar()
