# PAIOS — ARCHITECTURE

> Personal AI Operating System. An intelligent agent layer between the user and
> their machine: it understands the system, remembers, plans, and acts — under
> strict security controls.

This document is the authoritative architectural reference. Implementation
details that diverge from this doc are recorded in `DECISIONS.md`.

---

## 1. Design Principles

1. **Intelligence first, UI second.** The AI Core is the only thing that
   "thinks." Tools, memory, and UI are services it talks to.
2. **Modular by construction.** Every capability is a replaceable module behind
   an interface. The agent never imports a concrete tool or provider directly.
3. **Security by default.** Path validation, permission checks, command policy,
   audit logging, and user confirmation wrap every privileged action.
4. **Real functionality only.** No fake data, no simulated AI states. Every
   number shown in the UI comes from a real measurement.
5. **Professional quality.** The result should look and feel like a product.

---

## 2. System Overview

```
                    ┌──────────────────────────────────────────┐
                    │                FRONTEND                   │
                    │   React + TS, served locally by FastAPI   │
                    │  Console · System · Memory · Tasks ·      │
                    │  Tools · Projects · Settings              │
                    └───────────────┬──────────────┬───────────┘
                          REST API  │   WebSocket  │  (live events)
                    ┌───────────────▼──────────────▼───────────┐
                    │               API LAYER                   │
                    │          FastAPI (async ASGI)             │
                    └───────────────┬──────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
     ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
     │   AI CORE    │◄─────►│    MEMORY    │       │    TOOLS     │
     │              │       │              │       │  (sandboxed) │
     │ • Agent loop │       │ SQLite +     │       │ • FS         │
     │ • Planner    │       │ vector index │       │ • Sys monitor│
     │ • Context mgr│       │ • importance │       │ • Terminal   │
     │ • Task mgr   │       │              │       │ • Proj analy.│
     │ • Event bus  │       │              │       │              │
     └──────┬───────┘       └──────────────┘       └──────┬───────┘
            │                                              │
            ▼                                              ▼
     ┌──────────────┐                              ┌──────────────┐
     │  MODEL TIER  │                              │   SECURITY   │
     │ Tier-2: base │                              │ path policy  │
     │ Tier-1: micro│                              │ cmd policy   │
     │ (Ollama)     │                              │ audit log    │
     └──────────────┘                              │ confirmations│
                                                   └──────────────┘
```

---

## 3. AI CORE

The core is a streaming agent runtime. Three execution modes:

### 3.1 Agent (ReAct loop — simple tasks)

For single-step requests. Each iteration:

1. **Observe** — assemble context: user request + conversation + relevant
   memory + available tool schemas.
2. **Think** — the base model produces a reasoning trace + either a tool call
   or a final answer.
3. **Act** — if a tool call, route through Security → execute → append result
   to context.
4. **Loop** until a final answer is emitted or `max_iterations` is hit.

The Tier-1 intent router decides whether a request takes this path or goes to
the Planner. Until that micro-model is trained (Phase 2), a heuristic fallback
(heuristics on request length, keyword presence) is used.

### 3.2 Planner (complex tasks)

Decomposes a request into a **DAG of steps**:

```
User request
  → Planner generates plan (list of steps, each a sub-goal)
  → For each step: run through the ReAct loop
  → Verifier checks each step's output against its goal
  → On failure: re-plan that branch (up to N retries)
  → Synthesizer produces final report
```

Plan steps reference tools by name; the Planner is itself driven by the base
model prompted with the tool registry.

### 3.3 Context manager

Owns the rolling context window. Responsibilities:

- Truncate/summarize old conversation turns.
- Inject relevant memory (top-K by importance × recency × semantic similarity).
- Inject the schemas of tools the micro-model router predicts as relevant
  (reduces token cost vs. sending all tool schemas every turn).
- Enforce a hard token budget per provider.

### 3.4 Task manager

Long-lived task state machine:

```
created → planning → running → (verifying) → completed
                  ↘ failed
                  ↘ cancelled
```

Tasks persist across restarts. The API streams task transitions live.

### 3.5 Event bus

In-process async pub/sub. Every meaningful action (tool call, plan step,
memory write, task transition, confirmation request) emits an event. The API
layer subscribes and forwards to WebSocket clients. This single bus is what
makes the UI feel like "mission control."

---

## 4. MODEL TIER (Hybrid)

### 4.1 Tier-2 — Open-weights base model

Run locally via **Ollama**. Default `qwen2.5:3b-instruct`. Handles:

- Natural language understanding of requests
- ReAct reasoning traces
- Plan generation and step decomposition
- Result evaluation and final response synthesis
- Project analysis prose

Talks to the core through the `LLMProvider` interface, so any Ollama-pullable
model (or a cloud provider) can be swapped in.

### 4.2 Tier-1 — Custom-trained micro-models

Small, specialized models that are **cheaper and faster** than calling the base
model. You genuinely train these.

| Model | Purpose | Type | Phase |
|---|---|---|---|
| **Intent router** | Request → Simple / Complex / tool-domain | Classifier | 2 |
| **Command safety** | Shell command → FREE / CONFIRM / RESTRICTED | Classifier | 2 |
| **Tool selector** | Predicts relevant tool set from request | Ranker | 4 |
| **Memory importance** | Predicts vitality of a stored memory | Regressor | 4 |

**Training pipeline:** labeled datasets in `modeling/datasets/`, training
scripts in `modeling/train/`, a `modeling/registry.py` serves loaded models to
the core. Initial classifiers: scikit-learn (TF-IDF + logistic regression or
small MLP). Upgrade path: LoRA fine-tune on a small open transformer.

---

## 5. TOOL SYSTEM

Every tool conforms to:

```python
class Tool(ABC):
    name: str
    description: str
    permission: PermissionLevel   # FREE | CONFIRM | RESTRICTED
    schema: Type[BaseModel]       # Pydantic input schema → JSON Schema
    async def run(self, **kwargs) -> ToolResult: ...
```

- **Registry** auto-discovers `Tool` subclasses; the agent queries it by name
  or by semantic match. Adding a tool = creating a class; the agent never
  changes.
- **Permissions** gate execution (see Security).
- **Logging** — every invocation is recorded with inputs, outputs, duration,
  and outcome.

### Phase-1 tools

- `filesystem_read` — read files / list dirs inside sandbox roots (FREE)
- `system_monitor` — CPU / RAM / disk / processes via psutil (FREE)
- `terminal` — run commands from an allowlist (FREE / CONFIRM / RESTRICTED by
  command classification)

### Later tools

- `filesystem_write` (CONFIRM), `applications` (launch/inspect apps),
  `project_analyzer` (scan, detect stack, find TODOs, recommendations).

---

## 6. MEMORY & KNOWLEDGE

Hybrid memory store:

- **Structured** (SQLite/SQLModel): facts, preferences, project metadata,
  history records. Typed by category: `USER | PROJECT | HISTORY | SKILL`.
- **Semantic** (ChromaDB, embedded): embeddings of memory content for
  free-text recall.
- **Importance score** (0..1) attached to every memory. Drives retrieval
  ranking and decay.

Operations: store, retrieve, search (keyword + semantic), edit, delete,
re-score. The importance scorer (Phase 4) is a learned model; until then a
heuristic (recency × frequency-of-recall × user-flagged) is used.

---

## 7. SECURITY

Cross-cutting layer that wraps every tool call, not just terminal.

- **Path policy** — resolves and validates every filesystem path against the
  configured sandbox roots. Rejects traversal (`..`), symlinks pointing
  outside, and absolute paths outside roots.
- **Command policy** — classifies shell commands: FREE allowlist (read-only
  commands), CONFIRM (default), RESTRICTED (destructive: `rm`, `format`,
  `del`, `shutdown`). Phase-2 command-safety micro-model replaces the static
  classifier.
- **Confirmation flow** — CONFIRM actions emit a WebSocket event; the UI
  blocks execution until approval (120s timeout → auto-deny). RESTRICTED
  actions additionally require a reason string.
- **Audit log** — append-only structured JSON of every privileged action,
  with timestamp, inputs, user decision, and outcome. Stored under
  `backend/data/audit/`.
- **Never** arbitrary file access; **never** uncontrolled shell execution.

---

## 8. API LAYER

**FastAPI**, async ASGI.

- REST routes under `/api`: `/agent`, `/system`, `/memory`, `/tasks`,
  `/tools`, `/projects`, `/settings`.
- **WebSocket** `/ws` — bidirectional. Server pushes live events; client sends
  confirmation responses and cancellation signals.
- All request/response models are Pydantic; OpenAPI schema auto-generated.
- Serves the built React frontend from `/` in production mode.

---

## 9. FRONTEND

React + TypeScript + Vite. **Not** a dashboard — an operating interface.

| Page | Purpose |
|---|---|
| **AI Console** | Main workspace: conversation, live planning steps, tool execution viz, memory used, AI status |
| **System Intelligence** | Real CPU/GPU/RAM/storage/processes/health + recommendations |
| **Memory Center** | Browse / search / edit / delete memories by category & importance |
| **Task Center** | Active / completed / failed tasks, execution history |
| **Project Intelligence** | Scan projects, detected stack, structure, TODOs, recommendations |
| **Tool Center** | Browse tools, schemas, permission levels, recent invocations |
| **Settings** | Model config, sandbox roots, permissions, audit viewer |

State: Zustand (UI) + TanStack Query (REST cache). WebSocket hook for live
events. Styling: Tailwind CSS + a shadcn-style component set, dark
"mission-control" aesthetic.

---

## 10. DATA & PERSISTENCE

```
backend/data/
├── paios.db            # SQLite primary store
├── chroma/             # vector index
├── logs/               # rotating app logs
├── audit/              # append-only audit events
└── models/             # trained micro-model artifacts
```

All runtime data lives under `backend/data/` (gitignored). Timestamps stored as
UTC, rendered in local timezone in the UI.

---

## 11. CROSS-CUTTING CONCERNS

- **Logging** — Python `logging`, rotating files. Structured JSON for audit.
- **Configuration** — Pydantic `BaseSettings` from `.env` + `config.yaml`.
- **Error handling** — tools return `ToolResult(ok, output, error)`; the agent
  feeds errors back into reasoning. API errors are typed and consistent.
- **Testing** — pytest + pytest-asyncio (backend), Vitest + Playwright
  (frontend). Each phase ships with tests for its surface area.

---

## 12. THREAT MODEL (brief)

- **Untrusted tool output** (e.g. a malicious file the AI reads) — tools
  return data, the model is prompted to treat tool output as untrusted.
- **Prompt injection via files/memory** — context manager labels memory and
  tool outputs with their source; system prompt instructs the model to treat
  out-of-band instructions as data, not commands.
- **Privilege escalation via terminal** — command policy + confirmation +
  audit; no tool runs as a more privileged user than the PAIOS process.
- **Path escape** — path policy rejects traversal and out-of-root absolute
  paths before any FS operation.
