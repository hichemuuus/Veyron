# Changelog

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
- Updated all user-facing text, metadata, and graphics

## [1.2.0-alpha] — 2026-07-18

### Added
- **Issue 1 — Backend process lifecycle**: Window close handler (`on_window_event`), `RunEvent::Exit` handler, `Drop` impl for `BackendLauncher`, `shutdown()`/`wait_for_shutdown()` with 2s graceful + force-kill fallback
- **Issue 2 — Request logging middleware**: Per-request `METHOD PATH STATUS LATENCYms` logging, 30s timeout warnings, structured 500 error responses for unhandled exceptions
- **Issue 3 — Independent dashboard loading**: `Promise.allSettled` for dashboard API fetches (stats, recent tasks, system), per-section error states with retry buttons, graceful degradation when endpoints fail
- **Issue 5 — Diagnostics improvements**: Request history (last 20 API calls with method/path/status/duration/error/retries), developer mode toggle for stack traces, health check error capture
- **Test suite**: 16 new tests covering learning endpoint responsiveness, concurrent request isolation, request logging, dashboard structure, and lifespan shutdown

### Changed
- **Windows close cleanup**: X button, Alt+F4, tray Quit, and app exit all converge on `launcher.shutdown()` — no orphaned backend processes
- **Async DB calls**: All synchronous DB sessions in `api/routes/learning.py` wrapped in `asyncio.to_thread()` to prevent event loop blocking
- **Planner fixes**: 5 missing `await` keywords on `tracker` async calls added in `core/planner.py`
- **Shutdown robustness**: `scheduler.stop()` and `bus.shutdown()` wrapped in 10s `asyncio.wait_for()` with graceful error handling
- **API client dashboard**: Returns per-section nullables with individual error fields instead of single-throw behavior
- **Theme**: Replaced 7 hardcoded `bg-white` instances in `Settings.tsx` and `UpdateDialog.tsx` with theme tokens (`bg-ink-100`, `bg-sig-500`, `bg-ink-200`)
- **Diagnostics UI**: Uses API client instead of raw `fetch()`, shows real HTTP status/duration/error details instead of "Failed to fetch"

### Fixed
- Backend child processes orphaned on window close (Issue 1)
- `api/routes/learning.py` sync DB calls blocking async event loop (Issue 2)
- `core/planner.py` tracker calls silently fire-and-forget (Issue 2)
- Dashboard stuck loading when one API call fails (Issue 3)
- White background cards in dark theme (Issue 4)
- Diagnostics showing generic "Failed to fetch" instead of real errors (Issue 5)

### Added
- Enhanced reflection engine with confidence, planning quality, tool selection quality, parameter quality, and memory usefulness scoring
- Reflection records persisted to database with retrieval and aggregate statistics
- Long-term memory upgrades: importance scoring, enhanced merge engine, memory summarization, user profile generation
- Skill learning system: automatic detection of repeated workflow patterns from user history
- Workflow engine: reusable workflows with variables, conditions, retries, and failure policies
- Autonomous improvement: auto-detection of dataset growth, benchmark regression detection, model rollback, promotion guard (never deploy weaker)
- Plugin SDK: plugin base classes, registry with isolation, lifecycle management
- Example plugin demonstrating the SDK (hello_world tool)
- Learning Dashboard API: 11 read-only endpoints exposing reflection, skill, workflow, benchmark, model, and event data
- Learning Dashboard frontend page with 6 stat cards and 6 tabbed data views
- 5 benchmark test suites: reflection quality, memory quality, workflow prediction, skill detection, learning progress
- 9 new SQLModel tables: ReflectionRecord, Workflow, WorkflowStepModel, Skill, PluginRegistration, LearningEvent, BenchmarkRun, ModelVersion, MemoryCategory additions
- Configuration options for all learning & automation features

### Changed
- Enhanced MemoryStore with 7 new methods (importance scoring, similarity search, auto-merge, summarization, profile generation, extended stats)
- Enhanced MemoryScoring with aggregate summary and new-content scoring
- Enhanced RetrainingOrchestrator with regression detection, rollback, version history, dataset quality assessment, learning event recording
- Enhanced IntelligenceScheduler with auto-improvement cycle, scheduler status endpoint, manual trigger
- Updated frontend Layout with Learning nav item
- Updated frontend App with /learning route
- Updated frontend API client with 10 new learning API methods
- Updated frontend types with 16 new interfaces

### Fixed
- (see milestone reports for detailed fixes)
