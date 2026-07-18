# Veyron

**AI Productivity System** — a local-first agent runtime that understands your system, remembers, plans, and acts under strict security controls. Not a chatbot; an AI operating interface.

---

## Overview

Veyron is an intelligent agent layer between you and your computer. It runs entirely offline via Ollama, provides a ReAct reasoning loop for simple tasks and a DAG-based planner for complex multi-step work, and learns from every interaction through a training pipeline that improves its micro-models over time. Every filesystem read, terminal command, and tool call is gated by a security policy with path validation, command classification, user confirmation, and an append-only audit log.

The system is built as a modular FastAPI backend with an async event bus, a React + TypeScript frontend, and an optional Tauri v2 desktop shell.

---

## Core Features

- **ReAct Agent Loop** — observes, reasons, and acts iteratively. Streams `agent.thinking` events in real time so the UI can visualize the agent's thought process.
- **DAG Planner** — decomposes complex requests into a dependency graph of steps. Executes independent steps in parallel, verifies outputs with an LLM verifier, repairs failed steps inline (up to 3 failures), and falls back to full replan when needed.
- **Local LLM (Ollama)** — all reasoning, planning, and synthesis runs through an Ollama-hosted model. Default: `qwen2.5:3b-instruct`. Swappable via the `LLMProvider` interface.
- **Remote LLM Fallback** — when Ollama is unreachable and a remote provider is configured (OpenAI-compatible), the agent falls back transparently.
- **Micro-Model Intelligence** — five trained scikit-learn models (TF-IDF + Logistic Regression) that handle sub-second classification and routing without calling the base LLM:
  - **Intent Router** — classifies requests into domains (coding, system, memory, etc.) and selects ReAct vs. Planner mode.
  - **Tool Selector** — predicts which tools are relevant for a given request, reducing token cost by filtering tool schemas.
  - **Planning Model** — predicts whether a request needs planning (vs. a simple ReAct loop) and estimates step count.
  - **Memory Retrieval Reranker** — reranks candidate memories after SQL keyword search.
  - **Error Recovery** — classifies error patterns for recovery strategies.
- **Hybrid Memory** — persistent long-term memory backed by SQLite. Every memory has an importance score (0–1) that drives retrieval ranking and exponential decay. Memories are tagged by category (USER, PROJECT, HISTORY, SKILL, REFLECTION, PROFILE, WORKFLOW) and enriched with quality scores (usefulness, reliability, success frequency).
- **Active Learning** — every user interaction is saved as a JSONL record, optionally enriched with feedback scores, and periodically merged into the training dataset for automatic retraining.
- **MLflow Experiment Tracking** — every training run logs parameters, metrics, dataset hashes, and model artifacts to a local SQLite-backed MLflow instance.
- **Model Registry** — trained models are registered in a JSON file-based registry with a promotion gate: a new model must exceed the current production score by a configurable threshold (default: +0.01 on the primary metric) to be auto-promoted.
- **Reflection Engine** — after every task, the agent reflects on its performance, identifies mistakes, and stores improvement notes as memories. Reflection is always run on failures; successes are sampled at `reflection_sample_rate`.
- **Workflow Engine** — reusable, multi-step workflow definitions with conditions, variable templates, retries, and configurable failure policies (abort / skip / ignore). Workflows can be saved, versioned, and re-executed.
- **Plugin SDK** — `PluginBase` abstract class with a manifest system. Plugins can register custom tools, commands, and workflows. Discovered from the `plugins/` directory.
- **Tool System** — self-registering tool classes with Pydantic input schemas, retry logic, configurable timeouts, and safety evaluation. Current tools:
  - `filesystem_read` — read files, list directories, stat paths (FREE)
  - `system_monitor` — CPU, RAM, disk, processes, health checks via psutil (FREE)
  - `terminal` — sandboxed shell execution with per-command permission classification (FREE / CONFIRM / RESTRICTED)
  - `project_analyzer` — detect technologies, analyze structure, find issues (FREE)
- **Security Layer** — path validation against sandbox roots, command classification with static allowlist/denylist, user confirmation flow (CONFIRM actions gate via WebSocket, RESTRICTED actions require a reason), append-only audit logging to daily JSONL files.
- **REST API** — FastAPI with auto-generated OpenAPI docs at `/docs`. Endpoints for agent tasks, system info, tools, projects, memory, dashboard, intelligence metrics, and learning.
- **WebSocket API** — bidirectional event streaming at `/ws`. Server pushes live events (task transitions, tool calls, agent thinking deltas, confirmation requests); client sends subscribe/unsubscribe and confirmation responses.
- **Desktop Application** — optional Tauri v2 shell with system tray and backend lifecycle management.
- **Event Bus** — in-process async pub/sub that emits events for every meaningful action. The UI stays synchronized through a single WebSocket connection subscribed to the bus.

---

## Architecture

```
                      ┌──────────────────────────┐
                      │      FRONTEND (React)     │
                      │     React Router + TS     │
                      │   Zustand + TanStack      │
                      └──────┬──────────┬─────────┘
                        REST │ WebSocket │ (live events)
               ┌─────────────▼──────────▼──────────┐
               │           FASTAPI (ASGI)           │
               │  /api/agent · /api/system · /ws   │
               │  Auth · Rate-limit · Request IDs   │
               └─────────────────┬──────────────────┘
                                 │
        ┌────────────────────────┼──────────────────────┐
        ▼                        ▼                      ▼
┌───────────────┐      ┌──────────────────┐    ┌──────────────┐
│   AI CORE     │      │     MEMORY       │    │   TOOLS      │
│               │      │                  │    │  (sandboxed) │
│ Agent (ReAct) │◄────►│ SQLite store     │    │ filesystem   │
│ Planner (DAG) │      │ Importance       │    │ terminal     │
│ Context mgr   │      │ Decay + dedup    │    │ system_mon   │
│ Task manager  │      │ Merge + quality  │    │ proj_analyze │
│ Event bus     │      │ Summarization    │    │              │
│ Reflection    │      │ User profile     │    │              │
└───────┬───────┘      └──────────────────┘    └──────┬───────┘
        │                                              │
        ▼                                              ▼
┌───────────────────┐                        ┌──────────────────┐
│   MODEL TIER      │                        │    SECURITY      │
│                   │                        │                  │
│ Ollama (Tier-2)   │                        │ Path policy      │
│ scikit-learn (T1) │                        │ Command policy   │
│ 5 micro-models    │                        │ Confirmation     │
│ Model registry    │                        │ Audit log        │
│ MLflow tracking   │                        │ Risk classifier  │
└───────────────────┘                        └──────────────────┘
                                                      │
                                                      ▼
                                          ┌──────────────────┐
                                          │    LEARNING      │
                                          │                  │
                                          │ Skill detection  │
                                          │ Dataset quality  │
                                          │ Retrain scheduler│
                                          │ Training pipeline│
                                          │ (subprocess)     │
                                          └──────────────────┘
```

---

## Quick Start

### Prerequisites

- **Python 3.11–3.13**
- **uv** — `pip install uv` or see https://docs.astral.sh/uv
- **Ollama** (optional, for LLM features) — install from https://ollama.com

```bash
# Clone and enter the repository
git clone https://github.com/yourusername/veyron.git
cd veyron

# Create a virtual environment and install dependencies
uv venv --python 3.12
uv pip install -e ".[dev,ml]"

# Configure (optional — sensible defaults exist)
cp config.example.yaml config.yaml

# Pull the default model (optional)
ollama pull qwen2.5:3b-instruct

# Start the API server
uv run uvicorn veyron.main:app --reload
# → http://localhost:8000  (OpenAPI docs at /docs)
```

### Frontend (optional)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173 (proxies API to the backend)
```

### Desktop App (optional)

```bash
cd frontend/src-tauri
cargo build --release
```

### Training

```bash
# Generate synthetic training data
uv run python -m veyron.intelligence.training.generate_dataset

# Run the full training pipeline (intent classifier + tool selector)
uv run python -m veyron.intelligence.training.run_training

# Or train a single model
uv run python -m veyron.intelligence.train
```

### Benchmarks

```bash
uv run python -m veyron.intelligence.training.run_benchmark
```

### Tests

```bash
uv pip install -e ".[dev]"
uv run pytest -q
```

---

## Configuration

Settings are resolved in this order (highest precedence first):

1. **Environment variables** — `VEYRON_*` prefix, nested with `__` (e.g., `VEYRON_SERVER__HOST=0.0.0.0`)
2. **`.env` file** — key=value pairs in the project root
3. **`config.yaml`** — structured YAML in the project root
4. **Built-in defaults** — defined in `backend/veyron/config.py`

Key configuration groups:

| Section | Key Settings |
|---------|-------------|
| `security` | `sandbox_roots`, `approval_mode`, `confirm_timeout_seconds`, `agent_max_iterations`, `max_tool_output_chars` |
| `model` | `ollama_url`, `base_model`, `temperature`, `max_tokens`, `remote_enabled`, `remote_url`, `remote_api_key`, `micro_models_enabled` |
| `server` | `host`, `port`, `cors_origins`, `api_auth_token` |

See `config.example.yaml` for all available options.

---

## Project Structure

```
veyron/
├── pyproject.toml                  # Python dependencies and build config
├── ARCHITECTURE.md                 # Deep engineering reference
├── CONTRIBUTING.md                 # Contributor guide
├── DECISIONS.md                    # Design decision log
├── config.example.yaml             # Example configuration
├── LICENSE                         # MIT
│
├── backend/veyron/                 # FastAPI application root
│   ├── __init__.py                 # Version: 1.0.0
│   ├── main.py                     # App factory, lifespan, middleware, routes
│   ├── config.py                   # Pydantic Settings hierarchy
│   │
│   ├── api/                        # HTTP + WebSocket layer
│   │   ├── auth.py                 # verify_token() + FastAPI auth deps
│   │   ├── middleware.py           # Auth, rate-limit, request-ID middleware
│   │   ├── schemas.py             # Pydantic request/response models
│   │   ├── websocket.py           # /ws bidirectional event streaming
│   │   └── routes/                 # Route modules
│   │       ├── agent.py            # POST /api/agent, GET /api/agent/{id}, cancel, pause, resume
│   │       ├── system.py           # GET /api/system/overview
│   │       ├── tools.py            # Tool listing
│   │       ├── projects.py         # Project analysis
│   │       ├── memory.py           # Memory CRUD
│   │       ├── dashboard.py        # Dashboard metrics
│   │       ├── intelligence.py     # Intelligence metrics
│   │       └── learning.py         # Learning/skill endpoints
│   │
│   ├── core/                       # AI agent runtime
│   │   ├── agent.py                # ReAct loop, planner dispatch, interaction capture
│   │   ├── planner.py              # DAG planner: generation, validation, execution, repair, synthesis
│   │   ├── context.py              # System prompt builder, context window management
│   │   ├── events.py               # Async pub/sub event bus
│   │   ├── tracker.py              # Async task execution tracker
│   │   ├── task_manager.py         # Task state machine (sync, direct DB queries)
│   │   ├── reflection.py           # Post-task reflection engine
│   │   ├── evaluator.py            # Task evaluation and metric collection
│   │   └── intelligence.py         # Request classification (intent routing)
│   │
│   ├── db/                         # Database
│   │   ├── base.py                 # Sync + async engines, session factories, init_db()
│   │   └── models.py               # SQLModel tables: Task, Memory, AuditEvent, ToolInvocation,
│   │                               #   ExecutionStep, EvaluationMetric, ReflectionRecord,
│   │                               #   Workflow, WorkflowStepModel, Skill, PluginRegistration,
│   │                               #   LearningEvent, BenchmarkRun, ModelVersion, PredictionLog
│   │
│   ├── intelligence/               # ML models and training
│   │   ├── models/                 # Model registry (JSON file + service layer)
│   │   │   ├── registry.py         # Registry: register, promote, demote, get_production
│   │   │   └── schema.py           # ModelMetadata dataclass
│   │   ├── intent_router/          # Intent classification model
│   │   ├── tool_selector/          # Tool selection model
│   │   ├── planning/               # Planning necessity model
│   │   ├── memory_retrieval/       # Memory reranking model
│   │   ├── error_recovery/         # Error classification model
│   │   ├── training/               # Training pipeline V2
│   │   │   ├── run_training.py     # Full pipeline: load → train → MLflow → promote
│   │   │   ├── trainer_v2.py       # TrainingPipelineV2
│   │   │   ├── dataset.py          # TrainingDataset, UserInteraction, load/save/merge
│   │   │   ├── quality.py          # QualityScorer
│   │   │   ├── feedback.py         # Feedback loop
│   │   │   ├── generate_dataset.py # Synthetic data generation
│   │   │   ├── generate_llm_data.py# LLM-generated training queries
│   │   │   ├── retrain.py          # Retraining orchestration
│   │   │   ├── scheduler.py        # Background retraining scheduler
│   │   │   ├── collector.py        # Interaction collector
│   │   │   ├── exporter.py         # Dataset exporter
│   │   │   └── benchmark_v2.py     # Benchmark runner
│   │   ├── observability.py        # log_prediction(), resolve_model_version()
│   │   ├── scheduler.py            # IntelligenceScheduler (background retraining loop)
│   │   └── benchmark.py            # Benchmark base
│   │
│   ├── llm/                        # LLM provider abstraction
│   │   ├── base.py                 # LLMProvider ABC, Message, GenerateOptions
│   │   ├── ollama.py               # Ollama provider (streaming via httpx)
│   │   ├── remote.py               # Remote OpenAI-compatible provider
│   │   └── micro/                  # Micro-model router
│   │       └── router.py           # Intent dataclass + classify_request()
│   │
│   ├── memory/                     # Long-term memory system
│   │   ├── store.py                # MemoryStore: CRUD, search, recall, build_context
│   │   ├── importance.py           # Heuristic importance scorer (keyword-based)
│   │   ├── lifecycle.py            # Decay, duplicate detection, merge, cleanup
│   │   ├── merge.py                # MemoryMerger: find_and_merge_similar, execute
│   │   ├── scoring.py              # Quality scores (usefulness, reliability, success freq)
│   │   ├── summarization.py        # Extractive memory summarization
│   │   └── user_profile.py         # UserProfile generation from memories
│   │
│   ├── learning/                   # Learning and skill detection
│   │   ├── skill_detector.py       # Pattern detection from execution history
│   │   └── skill_store.py          # Skill persistence and retrieval
│   │
│   ├── security/                   # Security layer
│   │   ├── policy.py               # SafetyPolicy: risk classification + approval modes
│   │   ├── path_policy.py          # Sandbox path validation
│   │   ├── command_policy.py       # Shell command classification (FREE/CONFIRM/RESTRICTED)
│   │   ├── confirmations.py        # User confirmation flow
│   │   └── audit.py                # Append-only audit log (JSONL files)
│   │
│   ├── tools/                      # Tool system
│   │   ├── base.py                 # Tool ABC, ToolResult, ToolContext, safe_run()
│   │   ├── registry.py             # Auto-discovering ToolRegistry
│   │   ├── filesystem_read.py      # read_file, list_dir, stat
│   │   ├── terminal.py             # Sandboxed shell execution
│   │   ├── system_monitor.py       # psutil-based system inspection
│   │   └── project_analyzer.py     # Codebase analysis
│   │
│   ├── workflow/                   # Reusable workflow engine
│   │   ├── engine.py               # WorkflowEngine: execute() with conditions, retries, failure policies
│   │   ├── models.py               # WorkflowDefinition, WorkflowStep, WorkflowExecutionResult
│   │   └── registry.py             # WorkflowRegistry: save, get, list, record_execution
│   │
│   └── plugin/                     # Plugin system
│       ├── sdk.py                  # PluginBase, PluginManifest
│       └── registry.py             # PluginRegistry: discover, load, unload
│
├── frontend/                       # React + TypeScript + Vite + Tauri
│   ├── src/                        # React application
│   ├── src-tauri/                  # Tauri v2 desktop shell
│   ├── package.json                # npm dependencies
│   └── vite.config.ts              # Vite config with API proxy
│
├── benchmarks/                     # Performance benchmarks
├── tests/                          # pytest tests
│   ├── unit/                       # Unit tests (40+ test files)
│   ├── integration/                # Integration tests
│   └── benchmarks/                 # Learning/memory/reflection quality benchmarks
│
└── data/                           # Runtime data (gitignored)
    ├── veyron.db                   # SQLite database
    ├── models/                     # Trained model artifacts
    ├── training/                   # Training datasets, user interactions
    ├── logs/                       # Rotating application logs
    └── audit/                      # Append-only audit trail
```

---

## Development

### Testing

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run all tests
uv run pytest -q

# Run specific test categories
uv run pytest tests/unit/
uv run pytest tests/integration/
uv run pytest tests/unit/test_planner.py -v
```

### Formatting and Linting

```bash
# Ruff linting (matching CI)
ruff check backend/ tests/ benchmarks/

# Ruff is configured in pyproject.toml:
#   line-length = 100
#   target-version = "py311"
#   lint rules: E, F, I, UP, B, SIM
```

### Type Checking

```bash
# For TypeScript frontend
cd frontend && npm run typecheck
# For Rust desktop (if developing)
cd frontend/src-tauri && cargo build
```

### Benchmarks

```bash
# Run intelligence benchmarks
uv run python -m veyron.intelligence.training.run_benchmark

# Run system benchmarks
$env:PYTHONPATH="backend"
python -m benchmarks.runner --suite all
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (no auth required) |
| GET | `/api/info` | Version, tools, config (no auth required) |
| POST | `/api/agent` | Start a new agent task |
| GET | `/api/agent` | List tasks (filterable by status, mode) |
| GET | `/api/agent/{id}` | Task status + result + progress |
| GET | `/api/agent/{id}/timeline` | Execution step timeline |
| POST | `/api/agent/{id}/cancel` | Cancel a running task |
| POST | `/api/agent/{id}/pause` | Pause a running task |
| POST | `/api/agent/{id}/resume` | Resume a paused/failed task |
| DELETE | `/api/agent/{id}` | Delete a task permanently |
| POST | `/api/agent/{id}/feedback` | Submit user feedback score |
| GET | `/api/system/overview` | CPU/RAM/disk snapshot |
| GET | `/api/tools` | Tool schemas |
| POST | `/api/projects/analyze` | Analyze a project directory |
| GET | `/api/memory` | Search/list memories |
| POST | `/api/memory` | Store a new memory |
| GET | `/api/dashboard` | Task counts, system overview |
| GET | `/api/intelligence/metrics` | Micro-model metrics |
| GET | `/api/learning/overview` | Skills and learning progress |
| WS | `/ws` | Live events + confirmation flow |

---

## Roadmap

Veyron is developed in milestone phases. Implemented milestones:

- **Phase 1** — Foundation: FastAPI server, DB schema, event bus, memory store, tool registry, security layer, configuration system, desktop launcher, basic agent loop.
- **Phase 2** — Intelligence: micro-model training pipeline, intent router, tool selector, model registry with auto-promotion, MLflow integration, synthetic data generation, active learning with interaction capture.
- **Phase 3** — Planner: DAG-based step decomposition, parallel execution, LLM-based step verification, inline repair + full replan, quality scoring.
- **Phase 4** — Memory Depth: importance scoring, quality scoring (usefulness/reliability/success), exponential decay, duplicate detection, semantic merge, category summarization, user profile generation, memory reranker micro-model.
- **Phase 5** — Learning System: skill detection from execution patterns, workflow engine (conditional steps, retry policies, variable templates), auto-improvement background loop, plugin SDK with discovery and lifecycle management.
- **Phase 6** — Async Runtime: full async session migration for the event-loop path (agent, tracker, DB), background task scheduling (LLM diagnostics, retraining scheduler).

---

## License

MIT
