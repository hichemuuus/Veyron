# PAIOS

**Personal AI Operating System** — an intelligent agent layer between you and
your computer. It understands your system, remembers, plans, and acts under
strict security controls. Not a chatbot; an AI operating interface.

---

## Features

- **ReAct Agent Loop** — observes, reasons, and acts iteratively to complete tasks
- **Planner** — decomposes complex requests into DAGs of executable steps with verification and re-planning
- **Sandboxed Tool System** — filesystem read, system monitoring, terminal execution (all gated by security policy)
- **Security Layer** — path validation, command classification, user confirmation flow, append-only audit logging
- **Hybrid Memory** — structured (SQLite) with importance scoring, decay, deduplication, and semantic retrieval
- **Micro-Model Intelligence** — intent classification and tool selection via trained scikit-learn models (TF-IDF + Logistic Regression)
- **Mission-Control UI** — React + TypeScript + Vite frontend with live WebSocket event streaming
- **Local-First** — runs entirely offline via Ollama; no cloud dependency

## Architecture

```
Frontend (React+TS) ← WebSocket + REST → FastAPI API Layer
                                              ↓
                    ┌─────────────────────────┼─────────────────────┐
                    ↓                         ↓                     ↓
                AI Core                   Memory                Tools (sandboxed)
                ├─ Agent (ReAct)          ├─ SQLite store        ├─ filesystem_read
                ├─ Planner (DAG)          ├─ Chroma vectors      ├─ system_monitor
                ├─ Context manager        └─ Importance scoring  ├─ terminal
                ├─ Task manager                                └─ project_analyzer
                └─ Event bus
                    ↓                         ↓
                Model Tier                Security (cross-cutting)
                ├─ Tier-2: Ollama         ├─ Path policy
                └─ Tier-1: micro-models   ├─ Command policy
                  (classifiers)           ├─ Audit log
                                          └─ Confirmation flow
```

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLModel/SQLite, psutil |
| AI Core | Purpose-built ReAct loop + DAG Planner |
| Models | Tier-2: Ollama (local LLM) / Tier-1: scikit-learn micro-models |
| Frontend | React + TypeScript + Vite + Tailwind CSS |
| WebSocket | Live event streaming and confirmation flow |
| Security | Path validation, command classification, audit logging |

## Prerequisites

1. **Python 3.11–3.13**
2. **uv** — `pip install uv` or see https://docs.astral.sh/uv
3. **Ollama** (optional, for LLM features) — install from https://ollama.com
4. **Node.js 18+** (optional, for frontend development)

## Quickstart

```bash
# Clone the repository
git clone https://github.com/yourusername/paios.git
cd paios

# Install backend dependencies
uv venv --python 3.12
uv pip install -e ".[dev,ml]"

# Configure (optional — defaults work out of the box)
cp config.example.yaml config.yaml
cp .env.example .env

# Run the API
uv run uvicorn paios.main:app --reload
# → http://localhost:8000  (docs at /docs)
```

### Frontend (optional)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173 (proxies API to backend)
```

### Pull an Ollama model (for LLM features)

```bash
ollama pull qwen2.5:3b-instruct
```

## Configuration

Settings load from (highest precedence first):

1. Environment variables (`PAIOS_*`, `__` for nesting)
2. `.env` file in the project root
3. `config.yaml` in the project root
4. Built-in defaults in `backend/paios/config.py`

Key settings: sandbox roots, base model, Ollama URL, confirmation timeout.
See `config.example.yaml` for the full list.

## Security Model

- Every filesystem path is validated against configured **sandbox roots**
- Every shell command is classified **FREE / CONFIRM / RESTRICTED**
- CONFIRM actions gate via WebSocket confirmation flow
- RESTRICTED actions require approval + reason
- All privileged actions are written to an append-only audit log

## Project Layout

```
paios/
├── ARCHITECTURE.md           # Architecture reference
├── DECISIONS.md              # Design decisions log
├── ROADMAP.md                # Phase milestones
├── IMPLEMENTATION_PLAN.md    # Build plan
├── RELIABILITY.md            # Reliability targets
├── pyproject.toml            # Python dependencies
├── backend/paios/            # FastAPI + AI core + tools + memory + security
│   ├── api/                  # REST + WebSocket routes
│   ├── core/                 # Agent, Planner, Context, Events
│   ├── db/                   # SQLite models and session management
│   ├── intelligence/         # Micro-models (intent, tool selector)
│   ├── llm/                  # LLM provider interface + Ollama
│   ├── memory/               # Memory store, lifecycle, scoring
│   ├── security/             # Path policy, command policy, audit
│   ├── tools/                # Tool ABC, registry, implementations
│   └── scripts/              # Utility scripts
├── benchmarks/               # Performance and evaluation benchmarks
├── tests/                    # pytest unit + integration tests
└── frontend/                 # React + TypeScript + Vite UI
```

## Tests

```bash
uv pip install -e ".[dev]"
uv run pytest -q
```

Run benchmarks:

```bash
$env:PYTHONPATH="backend"
python -m benchmarks.runner --suite all
python -m benchmarks.perf
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/info` | Version, tools, config |
| GET | `/api/dashboard` | Task counts, system overview |
| POST | `/api/agent` | Start a new agent task |
| GET | `/api/agent` | List tasks (filterable) |
| GET | `/api/agent/{id}` | Task status + result |
| GET | `/api/agent/{id}/timeline` | Execution step timeline |
| POST | `/api/agent/{id}/cancel` | Cancel a running task |
| POST | `/api/agent/{id}/pause` | Pause a running task |
| POST | `/api/agent/{id}/resume` | Resume a paused/failed task |
| DELETE | `/api/agent/{id}` | Delete a task |
| GET | `/api/system/overview` | CPU/RAM/disk snapshot |
| GET | `/api/tools` | Tool schemas |
| POST | `/api/projects/analyze` | Analyze a project directory |
| WS | `/ws` | Live events + confirmations |

## License

MIT
