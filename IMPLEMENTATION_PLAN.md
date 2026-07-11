# PAIOS — IMPLEMENTATION PLAN

Step-by-step build order. Each step is small, testable, and committed before
the next begins. Phases map to `ROADMAP.md`.

Conventions:
- Backend deps via `uv`; frontend deps via `npm`.
- Every module has a docstring; every public function has a type annotation.
- New assumptions → log in `DECISIONS.md`.

---

# PHASE 1 — FOUNDATION

## 1.1 Project bootstrap
- [ ] `pyproject.toml` (Python 3.11+, FastAPI, uvicorn, SQLAlchemy 2,
      SQLModel, pydantic-settings, psutil, httpx, pytest, pytest-asyncio,
      chromadb [added Phase 2], ollama / httpx client)
- [ ] `.gitignore` (data/, .venv, node_modules, __pycache__, *.db)
- [ ] `backend/data/` subtree created and gitignored
- [ ] `backend/paios/__init__.py`, `backend/paios/config.py` (Pydantic settings)
- [ ] Sample `config.example.yaml` + `.env.example`
- [ ] `README.md` with quickstart

## 1.2 Database layer
- [ ] `db/base.py` — engine factory, session dependency
- [ ] `db/models.py` — initial tables: `task`, `memory`, `audit_event`,
      `tool_invocation`
- [ ] init_db helper that creates schema on first run

## 1.3 Event bus
- [ ] `core/events.py` — async pub/sub: `subscribe()`, `publish(event)`,
      per-subscriber `asyncio.Queue`. Event types defined as Pydantic models.

## 1.4 Security layer
- [ ] `security/path_policy.py` — `validate_path(path, roots) -> Path`
      resolving symlinks and rejecting escapes.
- [ ] `security/command_policy.py` — `classify_command(cmd) -> PermissionLevel`
      using a starter allowlist/denylist.
- [ ] `security/audit.py` — append-only JSON writer to `data/audit/`.
- [ ] `security/confirmations.py` — in-memory pending-confirmation registry
      keyed by request id; awaitable `request_confirmation()`.

## 1.5 Tool system
- [ ] `tools/base.py` — `Tool` ABC, `PermissionLevel` enum, `ToolResult`
      Pydantic model, schema-from-Pydantic helper.
- [ ] `tools/registry.py` — auto-discovery of `Tool` subclasses; `get(name)`,
      `all()`, `schemas_for(names)`.
- [ ] `tools/filesystem_read.py` — read file / list dir, path-policy gated.
- [ ] `tools/system_monitor.py` — psutil-backed CPU/RAM/disk/processes.
- [ ] `tools/terminal.py` — runs subprocess; permission from command policy;
      CONFIRM/RESTRICTED go through confirmation flow.

## 1.6 Model tier (initial)
- [ ] `llm/base.py` — `LLMProvider` interface (async `generate`,
      `generate_stream`, `embed`).
- [ ] `llm/ollama.py` — Ollama provider over HTTP (httpx), streaming support.
- [ ] `llm/micro/router.py` — heuristic intent router (Simple/Complex/domain)
      behind the same interface the Phase-2 trained model will satisfy.

## 1.7 AI Core — agent
- [ ] `core/context.py` — assembles prompt from request + memory (stub for
      now) + tool schemas.
- [ ] `core/agent.py` — ReAct loop: observe → think → act → loop; emits
      events at each step; max-iteration cap.
- [ ] Tool-call parsing from the model output (strict JSON function-call
      format prompted to the model).

## 1.8 API layer
- [ ] `main.py` — FastAPI app, CORS, route registration, static-frontend
      mount (placeholder).
- [ ] `api/routes/agent.py` — `POST /api/agent` (create task) and stream
      events for that task.
- [ ] `api/routes/system.py`, `/tools.py` — minimal listings.
- [ ] `api/websocket.py` — `/ws`: subscribe to event bus, receive
      confirmations, send responses.

## 1.9 Tests
- [ ] `tests/unit/test_path_policy.py` — traversal, symlink, absolute escape.
- [ ] `tests/unit/test_command_policy.py` — allowlist/denylist/unknown.
- [ ] `tests/unit/test_registry.py` — discovery + schema generation.
- [ ] `tests/unit/test_tools_*.py` — per tool, sandboxed inputs.
- [ ] `tests/integration/test_agent_e2e.py` — mocked LLM returns a tool call;
      verify tool runs, result feeds back, final answer emitted, events fired.

## 1.10 Phase 1 exit demo
- [ ] Run server, send "Show my CPU usage" via API → real stats return.
- [ ] Send "List files in <sandbox path>" → real listing.
- [ ] Trigger a CONFIRM command → WebSocket confirmation round-trips.

---

# PHASE 2 — INTELLIGENCE

## 2.1 Memory system
- [ ] `memory/models.py` — Memory SQLModel row (id, category, content,
      embedding_id, importance, created_at, ...).
- [ ] `memory/store.py` — CRUD + keyword search.
- [ ] `memory/vector.py` — Chroma collection, upsert/query via embeddings from
      `LLMProvider.embed`.
- [ ] `memory/importance.py` — heuristic scorer (recency × recall-count ×
      user-flag).
- [ ] `api/routes/memory.py` — full CRUD + search endpoints.

## 2.2 Planner
- [ ] `core/planner.py` — `plan(request, tools) -> list[PlanStep]` via base
      model; each step has a goal and suggested tool.
- [ ] Step executor: runs each step through the ReAct loop with a narrowed
      context.
- [ ] Verifier: base-model check of step output vs. step goal → pass/replan.
- [ ] Re-plan loop with retry cap.
- [ ] Synthesizer: final report from verified step outputs.

## 2.3 Task manager
- [ ] `core/task_manager.py` — lifecycle state machine, persistence,
      cancellation, history query.

## 2.4 Project analyzer
- [ ] `tools/project_analyzer.py` — scan a path: detect languages/frameworks
      (manifest files, extensions), structure summary, TODO/FIXME grep,
      recommendations (e.g. missing README, large dirs, stale deps).
- [ ] Exposed as a tool AND via `/api/projects/scan`.

## 2.5 First two micro-models
- [ ] `modeling/datasets/intent_router.jsonl`, `command_safety.jsonl` —
      labeled examples.
- [ ] `modeling/train/train_router.py` — TF-IDF + LogisticRegression (sklearn),
      save artifact to `data/models/`.
- [ ] `modeling/train/train_command_safety.py` — same family, 3-class.
- [ ] `modeling/registry.py` — load artifacts on demand, cache in memory.
- [ ] Replace heuristic routers with the trained models where available,
      falling back to heuristics if artifacts absent.
- [ ] `modeling/eval.py` — accuracy/precision/recall report; document
      baseline numbers in `DECISIONS.md`.

## 2.6 Tests
- [ ] memory CRUD + vector recall; planner decomposition on fixtures;
      project analyzer on a sample repo; micro-model eval thresholds.

---

# PHASE 3 — INTERFACE

## 3.1 Frontend bootstrap
- [ ] Vite React-TS app, Tailwind, base layout, dark theme tokens.
- [ ] API client (TanStack Query) + WebSocket hook (Zustand store for live
      events).
- [ ] Component library primitives (Button, Card, Panel, Badge, Modal,
      TreeView, CodeBlock, Sparkline).

## 3.2 Pages
- [ ] **AI Console** — conversation stream, planner-step timeline, tool-call
      cards (inputs/outputs/duration), memory-used chips, status indicator.
- [ ] **System Intelligence** — live CPU/GPU/RAM/disk gauges + top processes
      + health checks + recommendations panel.
- [ ] **Memory Center** — table by category, importance filter, search,
      edit/delete.
- [ ] **Task Center** — kanban of active/completed/failed + history drawer.
- [ ] **Tool Center** — catalog cards (schema, permission, last-used) +
      recent invocations.
- [ ] **Project Intelligence** — scan form, detected-stack chips, structure
      tree, TODO list, recommendations.
- [ ] **Settings** — model config, sandbox roots editor, permission defaults,
      audit log viewer.

## 3.3 Real-time + confirmations
- [ ] WebSocket event routing to pages.
- [ ] Confirmation modal flow (approve/deny + reason for RESTRICTED).
- [ ] Live tool-execution animation.

## 3.4 Tests
- [ ] Vitest component tests for Console + confirmation flow.
- [ ] Playwright E2E: send a request, see tool execute, approve a CONFIRM.

---

# PHASE 4 — ADVANCED

## 4.1 Remaining micro-models
- [ ] Tool selector dataset + training (ranker over tool schemas).
- [ ] Memory importance regressor; replace heuristic scorer.
- [ ] LoRA fine-tune path on a small open transformer (documentation +
      training script + optional use).

## 4.2 Proactive assistance
- [ ] Event sources: high CPU, low disk, stale project, idle time.
- [ ] Suggestion engine: emits "offer" events surfaced as toasts/cards in
      Console.

## 4.3 Automation
- [ ] Scheduler (cron-like) driving tasks on a schedule or event.
- [ ] `/api/automations` CRUD + UI.

## 4.4 Voice I/O (optional)
- [ ] Whisper (local) for input; TTS for output; mic button in Console.

## 4.5 Optional desktop wrapper
- [ ] Tauri shell around the web app; system tray; global hotkey.

## 4.6 Hardening & polish
- [ ] Full audit-review pass; penetration-style tests on tool layer.
- [ ] Performance profiling of agent loop + streaming.
- [ ] Documentation: user guide + admin guide.
