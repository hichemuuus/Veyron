# Changelog

## [1.0.0] — 2026-07-18

### Added
- Repository cleanup: removed 23 auto-generated reports, build artifacts, caches, screenshots
- `docs/` directory with 9 canonical documents (architecture, installation, AI models, testing, troubleshooting, design decisions, development history, roadmap, demo)
- Professional README with Mermaid architecture diagram
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, RELEASE_CHECKLIST.md
- `benchmarks/README.md` and `examples/README.md`
- `.gitignore` entries for `mlruns/`, `RELEASE_CHECKLIST.md` exclusion

### Changed
- Root package.json name `paios` → `veyron`
- Legacy docs (ARCHITECTURE.md, ROADMAP.md, DECISIONS.md, IMPLEMENTATION_PLAN.md) now point to canonical `docs/` versions
- All version numbers synchronized to 1.0.0 across backend, frontend, Cargo.toml, tauri.conf.json

## [1.2.0-alpha] — 2026-07-18

### Added
- **Backend process lifecycle**: Window close handler, `RunEvent::Exit` handler, `Drop` impl for `BackendLauncher`, graceful shutdown with force-kill fallback
- **Request logging middleware**: Per-request `METHOD PATH STATUS LATENCYms` logging, 30s timeout warnings, structured 500 error responses
- **Independent dashboard loading**: `Promise.allSettled` for dashboard API fetches, per-section error states with retry buttons
- **Diagnostics improvements**: Request history (last 20 API calls), developer mode toggle, health check error capture
- **Test suite**: 16 new tests (learning endpoint, concurrent requests, logging, dashboard, shutdown)

### Changed
- Windows close cleanup: X button, Alt+F4, tray Quit all converge on `launcher.shutdown()`
- Async DB calls: synchronous sessions wrapped in `asyncio.to_thread()`
- Planner: 5 missing `await` keywords added on tracker async calls
- Shutdown robustness: `scheduler.stop()` and `bus.shutdown()` wrapped in 10s timeout
- Theme: replaced 7 hardcoded `bg-white` instances with dark theme tokens

### Fixed
- Orphaned backend child processes on window close
- `api/routes/learning.py` sync DB calls blocking event loop
- Dashboard stuck loading when one API call fails
- White background cards in dark theme
- Diagnostics showing generic "Failed to fetch"

## [1.0.0-alpha] — 2026-07-15

### Added
- ReAct agent loop with DAG-based planner
- Hybrid memory (SQLite + importance scoring + decay)
- Sandboxed tool system (filesystem, terminal, system monitor)
- Security layer (path validation, command classification, audit log)
- Micro-model intelligence (intent classifier, tool selector)
- Ollama integration for local LLM inference
- REST API + WebSocket event streaming
- React + TypeScript + Vite frontend (Mission Control)
- Tauri v2 desktop shell with system tray, backend launcher, updater
- Benchmark suite (performance + agent evaluation)
- Trained model pipeline (7 micro-models)

### Changed
- Rebranded from PAIos to Veyron
- Migrated desktop shell from Electron to Tauri v2
