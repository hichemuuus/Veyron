# Veyron — Roadmap

High-level milestones. Detailed step-by-step plan is in `IMPLEMENTATION_PLAN.md`.

---

## Phase 1 — Foundation *(working agent loop, end-to-end)*

**Goal:** a request goes in, the AI reasons, calls real tools, and returns a
real answer — all under security controls, all visualizable.

Deliverables:
- Repo + dependency manifests (`pyproject.toml`, `package.json`)
- Configuration system (`.env`, `config.yaml`, Pydantic settings)
- SQLite + SQLModel schema + migrations
- FastAPI app skeleton: health check, REST route registration, WebSocket
- Tool system: `Tool` ABC, registry, permission enum, audit logging
- Three tools: `filesystem_read`, `system_monitor`, `terminal`
- Security layer: path policy, command policy, confirmation flow
- Model tier: Ollama integration (`LLMProvider`), heuristic intent router
- Agent: ReAct loop wired to `/api/agent`, streaming events to WebSocket
- Tests: unit (tools, security, agent) + integration (agent end-to-end)

**Exit criteria:** from a single API call, "Show my CPU usage" returns real
CPU stats; "What's in this folder?" returns a real listing; a CONFIRM-gated
command triggers a WebSocket confirmation and blocks until answered.

---

## Phase 2 — Intelligence *(planning, memory, project understanding)*

**Goal:** the AI handles complex multi-step requests, remembers across
sessions, and understands software projects.

Deliverables:
- Planner: DAG decomposition, step execution via ReAct, verifier, re-plan
- Hybrid memory: structured store + Chroma vector index + importance heuristic
- Memory CRUD + search API
- Task manager: lifecycle, persistence, history
- Project analyzer tool: scan, technology detection, structure analysis, TODO
  finding, recommendation generation
- **Tier-1 micro-models (first two):** intent router, command safety
  classifier — with datasets and training scripts
- Tests for all of the above

**Exit criteria:** "Analyze my project and prepare a report" produces a
multi-step plan, runs real tools, and returns a real report; memories persist
across server restarts; the micro-models hit documented accuracy targets.

---

## Phase 3 — Interface *(full frontend, mission-control feel)*

**Goal:** the whole system is operable through a polished UI.

Deliverables:
- React + TS + Vite scaffold, Tailwind, component library
- AI Console: conversation, live plan/tool visualization, memory inspector
- System Intelligence: live system metrics + recommendations
- Memory Center: browse / search / edit / delete
- Task Center: lifecycle views + history
- Tool Center: tool catalog + recent invocations
- Project Intelligence: scan UI + report rendering
- Settings: model config, sandbox roots, permissions, audit viewer
- WebSocket integration: live events + confirmation dialogs
- Vitest unit tests + Playwright E2E for critical flows

**Exit criteria:** every Phase 1–2 capability is operable from the UI with
zero raw API calls; confirmations and live updates work in real time.

---

## Phase 4 — Advanced *(proactive, automated, personalized)*

**Goal:** Veyron acts less like a responder and more like an operator.

Deliverables:
- Remaining Tier-1 micro-models: tool selector, memory importance scorer
- LoRA fine-tuning path for a small open transformer on Veyron-specific data
- Proactive assistance: event-driven suggestions (e.g. high CPU → offer
  diagnosis; stale project → offer analysis)
- Automation / scheduled tasks (cron-like triggers)
- Voice I/O (optional)
- Optional: Tauri desktop wrapper (system tray, global hotkey)

**Exit criteria:** Veyron volunteers useful actions without being prompted;
scheduled jobs run reliably; voice path works end-to-end where implemented.

---

## Cross-cutting (ongoing, every phase)

- `DECISIONS.md` updated as assumptions are made
- Tests accompany every feature
- Security review before each phase exits
- `README.md` kept current with run/dev instructions

---

## Phase 17 — Learning & Automation ✅ *(2026-07-15)*

**Goal:** Veyron continuously improves from real user interactions.

Deliverables:
- Reflection Engine — structured post-task analysis with confidence, planning quality, tool selection quality, parameter quality, memory usefulness scoring; persisted to DB with retrieval and aggregate stats
- Long-Term Memory — importance scoring, duplicate detection, memory merging, summarization, decay/pruning, user profile generation
- Skill Learning — automatic detection of repeated workflow patterns from user history
- Workflow Engine — reusable workflows with variables, conditions, retries, failure policies
- Autonomous Improvement — dataset growth detection, benchmark regression detection, model version rollback, promotion guard (never deploy weaker)
- Plugin SDK — plugin base classes, registry with isolation, lifecycle management, example plugin
- Learning Dashboard — 11 read-only API endpoints + frontend page with stat cards and tabbed data views
- Benchmark Suites — 5 suites: reflection quality, memory quality, workflow prediction, skill detection, learning progress

**Exit criteria:** All 8 components implemented and tested; 567+ existing tests pass; 30 benchmark tests pass; no APIs broken; no backend contracts changed.
