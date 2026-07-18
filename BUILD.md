# Veyron Desktop — Build Guide

## Prerequisites

| Component | Requirement | Check |
|-----------|-------------|-------|
| Rust | 1.77+ (`rustup install stable`) | `rustc --version` |
| Node.js | 18+ | `node --version` |
| Python | 3.11 – 3.13 | `python --version` |
| uv | latest | `uv --version` |
| WebView2 | Windows 10+ (built-in) | — |

## Development Build

### 1. Setup Python backend

```bash
cd veyron
uv sync                    # Install Python dependencies
uv sync --group dev        # Install dev dependencies (pytest, etc.)
```

### 2. Setup frontend

```bash
cd frontend
npm install                # Install JS dependencies
```

### 3. Run in development mode

```bash
cd frontend
npm run tauri:dev
```

This will:
- Start the Vite dev server on `http://localhost:5173`
- Compile and launch the Tauri desktop window
- Tauri spawns `uvicorn veyron.main:app` as a child process

The desktop window loads from `devUrl` (`http://localhost:5173`).  
The frontend proxies `/api` and `/ws` to the backend at `http://127.0.0.1:8000`.

## Release Build

### 1. Build the Python backend sidecar

```bash
python scripts/build_backend.py
```

This uses **PyInstaller** to compile the Python backend into a standalone executable:
- Output: `frontend/src-tauri/binaries/veyron-backend-x86_64-pc-windows-msvc.exe`
- Includes all Python dependencies, FastAPI, Uvicorn, etc.
- Does NOT include Ollama or LLM model files

### 2. Build the desktop installer

```bash
cd frontend
npm run tauri:build
```

This will:
1. Build the React frontend (`npm run build` → `frontend/dist/`)
2. Compile the Rust Tauri application in release mode
3. Package the application with the sidecar binary
4. Generate a Windows NSIS installer

**Output:**
```
frontend/src-tauri/target/release/
├── Veyron.exe              # Standalone executable
└── bundle/
    └── nsis/
        └── Veyron_1.0.0_x64-setup.exe   # Windows installer
```

### 3. Install

Run the NSIS installer. It installs Veyron to `%LOCALAPPDATA%\Veyron`  
(current-user mode, no admin required).

## Release Workflow

### Prerequisites: Updater signing key

The production updater requires a signing key pair. The public key is embedded in
`tauri.conf.json`; the private key must be available at build time.

**Generate a new keypair** (one-time per project):

```bash
npx tauri signer generate -w ./veyron-updater-key.private
```

**Keep the private key secret and backed up.** It controls update authenticity.

### Creating a new release

1. Bump version in:
   - `frontend/src-tauri/Cargo.toml`
   - `frontend/src-tauri/tauri.conf.json`
   - `frontend/package.json`
   - `pyproject.toml`
   - `backend/veyron/__init__.py`

2. Build the sidecar:
   ```bash
   python scripts/build_backend.py
   ```

3. Build the desktop installer (signed):
   ```bash
   cd frontend
   $env:TAURI_SIGNING_PRIVATE_KEY_PATH = "..\..\veyron-updater-key.private"
   $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "veyron-release-2026"
   npm run tauri:build
   ```
   On Linux/macOS:
   ```bash
   cd frontend
   TAURI_SIGNING_PRIVATE_KEY_PATH="../../veyron-updater-key.private" \
   TAURI_SIGNING_PRIVATE_KEY_PASSWORD="veyron-release-2026" \
   npm run tauri:build
   ```

4. The build produces:
   - `src-tauri/target/release/Veyron.exe` — standalone executable
   - `src-tauri/target/release/bundle/nsis/Veyron_1.0.0_x64-setup.exe` — signed NSIS installer
   - `src-tauri/target/release/bundle/nsis/Veyron_1.0.0_x64-setup.exe.sig` — update signature

5. Create a GitHub Release with the installer and `.sig` file.

### Update system

Veyron checks for updates via:
1. **Tauri updater plugin** (primary) — configured endpoint
2. **GitHub Releases API** (fallback) — `https://api.github.com/repos/anomalyco/veyron/releases/latest`

To publish an update:
1. Build the installer with signing env vars set (see above)
2. Upload the NSIS installer AND the `.sig` file to the GitHub Release
3. Ensure the release tag follows semver (`v1.1.0`, `v2.0.0`, etc.)
4. Veyron users will be notified on next startup

## Project Structure (Desktop)

```
veyron/
├── frontend/
│   ├── src/                    # React frontend
│   ├── src-tauri/              # Tauri desktop shell
│   │   ├── Cargo.toml
│   │   ├── tauri.conf.json
│   │   ├── capabilities/
│   │   ├── icons/              # App icons (generated)
│   │   ├── binaries/           # Sidecar binaries (built)
│   │   └── src/
│   │       ├── main.rs         # Entry point
│   │       ├── lib.rs          # Setup, commands
│   │       ├── launcher.rs     # Backend process manager
│   │       ├── tray.rs         # System tray
│   │       ├── updater.rs      # Update checking
│   │       └── config.rs       # User config
│   ├── dist/                   # Built frontend
│   └── package.json
├── backend/
│   └── veyron/                 # Python backend
├── scripts/
│   ├── build_backend.py        # PyInstaller sidecar builder
│   └── generate_icons.py       # App icon generator
└── pyproject.toml
```

## User Data

User data is stored separately from the application:

| OS | Data Directory |
|----|---------------|
| Windows | `%APPDATA%\Veyron\` |
| macOS | `~/Library/Application Support/Veyron/` |
| Linux | `~/.local/share/veyron/` |

Contains:
- `config.json` — User preferences
- `veyron.db` — SQLite database (memory, history)
- `logs/` — Application logs
- `models/` — Trained micro-models

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "WebView2 not found" | Install WebView2 (pre-installed on Windows 10+), or run the Evergreen bootstrapper |
| "Sidecar not found" | Run `python scripts/build_backend.py` before `npm run tauri:build` |
| "Ollama not available" | Install Ollama from `https://ollama.ai` and pull a model (`ollama pull qwen2.5:3b-instruct`) |
| "Backend failed to start" | Check logs in `%APPDATA%\Veyron\logs\` or run manually: `uvicorn veyron.main:app` |
