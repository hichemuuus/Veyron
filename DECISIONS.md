# PAIOS — DECISIONS LOG

Running log of assumptions and decisions made during autonomous build.
Per the autonomy directive, these are noted here rather than asked.

Format: `[DATE] DECISION — rationale`

---

## Foundational decisions (from initial planning)

[2026-07-11] PACKAGING — Local web app. FastAPI serves the React UI at `localhost:8000`. No desktop wrapper for v1; Tauri/Electron remains a future option without rearchitecting.

[2026-07-11] LOCATION — Project root is `paios/` at the repository root.

[2026-07-11] MODEL STRATEGY — Hybrid. Tier-1: small custom-trained micro-models (router, tool selector, command safety, memory importance). Tier-2: open-weights base model via Ollama (default Phi-3.5-mini / Qwen2.5-3B). No pretraining-from-scratch for general reasoning.

[2026-07-11] NO HEAVY AGENT FRAMEWORK — Purpose-built ReAct loop + planner instead of LangChain/LangGraph. Keeps the system transparent and avoids abstraction debt.

[2026-07-11] LANGUAGE — Backend Python 3.11+; Frontend React + TypeScript + Vite.

[2026-07-11] DB — SQLite via SQLAlchemy 2.0 + SQLModel. Vector store: embedded ChromaDB.

## Implementation decisions (per build step)

[2026-07-11] DEPENDENCY MANAGEMENT — `pyproject.toml` with `uv` for backend, `npm` for frontend. Chosen for speed and reproducibility.

[2026-07-11] PYTHON PROJECT LAYOUT — `src`-less layout (`backend/paios/...`) chosen over `src/paios/...` for simpler imports during early development; will revisit if packaging becomes an issue.

[2026-07-11] SETTINGS MANAGEMENT — Pydantic `BaseSettings` reading from `.env` + a `config.yaml` fallback. All tunable values live in one place.

[2026-07-11] EVENT BUS — In-process async pub/sub (`asyncio.Queue` per subscriber) for v1. Will swap for a real broker (Redis) only if cross-process scaling is ever needed (unlikely for a personal OS).

[2026-07-11] TOOL PERMISSION GATING — FREE tools run silently; CONFIRM tools emit a WebSocket confirmation request and block until user responds (timeout 120s → auto-deny); RESTRICTED tools require explicit UI approval AND a per-session reason string logged to audit.

[2026-07-11] COMMAND POLICY STARTER — Terminal tool uses an allowlist of read-only commands (ls, cat, git status, etc.) as FREE; anything else is CONFIRM by default; destructive commands (rm, format, del, shutdown) are RESTRICTED. The command-safety micro-model (Phase 2) replaces the static allowlist with a learned classifier.

[2026-07-11] SANDBOX ROOTS — Configurable list of allowed filesystem paths (default: the user's home dir + project root). Any path traversal attempt outside roots is rejected and logged. No blanket filesystem access.

[2026-07-11] TIMEZONE — All timestamps stored as timezone-aware UTC; rendered in the frontend using the browser's local timezone.

[2026-07-11] DEFAULT BASE MODEL — `qwen2.5:3b-instruct` via Ollama as the Tier-2 default (small enough for consumer GPUs, strong instruction-following). Phi-3.5-mini as documented alternative. Configurable in Settings.

[2026-07-11] MICRO-MODEL STACK — scikit-learn + PyTorch depending on model complexity. Router/safety classifiers start as sklearn (TF-IDF + logistic regression / small MLP); upgrade path to fine-tuned transformers via LoRA reserved for Phase 4.

[2026-07-11] LOGGING — Python `logging` to rotating files in `backend/data/logs/` + structured JSON for audit events in `backend/data/audit/`. Frontend uses the same event stream for live display.

[2026-07-11] PLANNER IMPLEMENTATION — Multi-step decomposition uses the same LLM provider for plan generation, step execution, verification, and synthesis. Step execution runs a mini ReAct loop (up to 6 tool calls per step) with narrowed context, rather than the full agent. Verification is LLM-based (PASS/FAIL) with optimistic fallback on errors. Retry cap of 2 re-plans per step.
