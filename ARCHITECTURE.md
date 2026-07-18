# Veyron — Architecture

**AI Productivity System.** A local-first agent runtime with memory, tools, micro-model intelligence, and a mission-control UI.

This document is the authoritative implementation reference. Every statement is derived from the codebase at `backend/veyron/`. If this document disagrees with earlier documentation, trust the code.

---

## 1. Design Principles

1. **Intelligence first, UI second** — The AI Core (agent + planner + memory) is the only component that reasons. The frontend, tools, and database are services it talks to through defined interfaces.
2. **Modular by construction** — Every capability sits behind an interface (`LLMProvider`, `Tool`, `PluginBase`). The agent never imports a concrete provider or tool class directly. Adding a feature means adding a class; the agent never changes.
3. **Security by default** — Path validation, command classification, permission levels, user confirmation, and append-only audit logging wrap every privileged action.
4. **Real measurements only** — Every system metric, file read, and command output comes from an actual measurement. No fake data.
5. **Local-first, offline capable** — The entire system runs on localhost with Ollama. A remote LLM provider (OpenAI-compatible) is available as a configurable fallback.

---

## 2. System Overview

```
                    ┌──────────────────────────────────────────┐
                    │              FRONTEND (React)            │
                    │   AI Console · Memory · Tasks · Tools    │
                    │   System · Projects · Intelligence       │
                    └──────────────┬───────────┬───────────────┘
                          REST API │ WebSocket │ (live events)
                                  │           │
                    ┌──────────────▼───────────▼───────────────┐
                    │            API LAYER (FastAPI)            │
                    │  /api/agent · /api/system · /ws · auth   │
                    └────────────────────┬─────────────────────┘
                                         │
            ┌────────────────────────────┼────────────────────────┐
            ▼                            ▼                        ▼
    ┌───────────────┐          ┌─────────────────┐      ┌──────────────┐
    │   AI CORE     │          │    MEMORY        │      │   TOOLS     │
    │               │          │                  │      │ (sandboxed) │
    │ Agent (ReAct) │◄────────►│ SQLite store     │      │ filesystem  │
    │ Planner (DAG) │          │ Importance       │      │ terminal    │
    │ Context mgr   │          │ Decay + dedup    │      │ sys_monitor │
    │ Task manager  │          │ Quality scoring  │      │ proj_analy  │
    │ Event bus     │          │ Merge + summary  │      │             │
    │ Reflection    │          │ User profile     │      │             │
    └───────┬───────┘          └─────────────────┘      └──────┬───────┘
            │                                                  │
            ▼                                                  ▼
    ┌───────────────────┐                            ┌──────────────────┐
    │   MODEL TIER      │                            │   SECURITY       │
    │                   │                            │                  │
    │ Tier-2: Ollama    │                            │ Path policy      │
    │ Tier-1: micro     │                            │ Command policy   │
    │ (5 scikit-learn)  │                            │ Confirmation     │
    │ Model Registry    │                            │ Audit log        │
    │ MLflow tracking   │                            │ Risk classifier  │
    └───────────────────┘                            └──────────────────┘
```

## 3. Request Lifecycle

```
User sends POST /api/agent {"request": "what's my CPU usage?"}

  1. API route (agent.py:create_task) creates a DB Task record (status=created)
     and schedules the agent run as a BackgroundTask.

  2. Agent.run() calls classify_request() → returns Intent with mode, domain,
     confidence, and predicted tools.

  3. The intent router (core/intelligence.py) loads the production intent
     classifier model (scikit-learn Pipeline) and the production tool selector.
     If micro-models are disabled, falls back to keyword heuristics.

  4. Mode == "react" → Agent._run_react():
     a. Assemble initial messages: system prompt + tool schemas (optionally
        filtered by predicted tools) + user request.
     b. Loop: generate_stream() → parse tool_call → safe_run() → append result.
     c. Stream agent.iteration, agent.thinking, tool.request, tool.result events.
     d. On final answer: save_interaction(), _maybe_reflect() (background).

  5. Mode == "plan" → Agent._run_planner():
     a. Optionally consult the planning micro-model for confidence check.
     b. Planner.plan_and_execute() → generate steps → validate → execute DAG →
        verify steps → repair failures → synthesize.
     c. Stream plan.start, plan.created, plan.step.*, plan.synthesized events.

  6. After completion (success or failure):
     a. _save_interaction() writes a JSONL record to data/training/user_interactions/.
     b. _maybe_reflect() schedules a background reflection task (LLM call) that
        analyses performance and stores improvement notes as memories.
```

### Sequence Diagram — ReAct Task

```
Client          API            Agent          LLM          Tools          DB
  │               │              │              │             │            │
  │ POST /agent   │              │              │             │            │
  │──────────────►│ create_task  │              │             │            │
  │               │─────────────►│              │             │            │
  │               │◄───{id,created}            │             │            │
  │◄───202 Created│              │              │             │            │
  │               │              │ classify     │             │            │
  │               │              │──────────────►            │            │
  │               │              │◄───Intent    │             │            │
  │               │              │              │             │            │
  │               │              │───[ReAct loop]             │            │
  │               │              │              │             │            │
  │  WS: iteration│  Event Bus   │ generate     │             │            │
  │◄──────────────│◄─────────────│─────────────►│             │            │
  │               │              │              │             │            │
  │               │              │    tool_call │             │            │
  │               │              │◄─────────────│             │            │
  │               │              │              │ safe_run    │            │
  │               │              │              │────────────►│            │
  │  WS: tool.result             │◄─────────────│             │            │
  │◄──────────────│◄─────────────│              │             │            │
  │               │              │              │             │            │
  │               │              │ [next iter]  │             │            │
  │               │              │              │             │            │
  │               │              │   answer     │             │            │
  │               │              │◄─────────────│             │            │
  │               │              │              │             │            │
  │  WS: answer   │              │ _complete    │             │            │
  │◄──────────────│◄─────────────│──────────────│────────────►│            │
  │               │              │ _save_inter  │             │            │
  │               │              │──────────────│────────────►│            │
```

## 4. AI Core

### 4.1 Agent (`core/agent.py`)

The `Agent` class is stateless between runs. All state lives in the `Task` DB table.

- `run(request, task_public_id)` — entry point. Enforces a 300-second wall-clock timeout via `asyncio.wait_for`. Returns `AgentRunResult`.
- `_run_with_timeout()` — classifies intent, routes to `_run_react()` or `_run_planner()`.
- `_run_react()` — standard ReAct loop up to `max_iterations` (configurable, default 12). Each iteration:
  1. Publish `agent.iteration` event.
  2. Save checkpoint to DB (iteration + tool call count).
  3. `_generate()` — calls `provider.generate_stream()` with tool schemas. Accumulates text deltas and emits `agent.thinking` events.
  4. If a tool call is returned: validate tool exists, create `ToolContext`, call `tool.safe_run()`, publish `tool.result` event, append to message history.
  5. If no tool call: treat accumulated text as the final answer, publish `agent.answer`, persist, save interaction, trigger reflection.
  6. If max iterations reached: publish `agent.exhausted`, persist failure.
- `_run_planner()` — delegates to `Planner.plan_and_execute()`.
- `_generate()` — streams from the LLM provider, emits text deltas every ~40 chars for live UI rendering.
- `cancel()` — adds task to cancellation set. Background reflection tasks are also cancelled.
- `_save_interaction()` — serializes a `UserInteraction` record to the daily JSONL file for training feedback. Captures timeline, quality score, latency breakdown, and router confidence.
- `_maybe_reflect()` — schedules background reflection. Always on failure; samples at `reflection_sample_rate` (default 0.2) on success.

### 4.2 DAG Planner (`core/planner.py`)

The `Planner` decomposes complex requests into a dependency graph of steps.

**Plan Generation (`_generate_plan`):**
- Prompts the LLM with a structured planner prompt listing available tools.
- Parses the LLM response — first attempts JSON array of step objects with `id`, `goal`, `tool`, `depends_on` fields; falls back to a numbered list parser.
- Returns a `Plan` with a list of `PlanStep` objects.

**Plan Validation (`_validate_plan`):**
- Rejects empty plans.
- Detects circular dependencies via DFS.
- Detects references to non-existent step IDs.
- Warns about unknown suggested tools (not fatal).

**DAG Execution (`_execute_dag`):**
- Maintains a set of remaining steps. At each cycle, identifies steps whose dependencies are all satisfied.
- Executes ready steps in parallel via `asyncio.gather()`.
- After execution, checks for failures:
  - If fewer than 3 steps failed: calls `_repair_step()` which asks the LLM to generate a replacement step, adds it to the plan, and updates dependency references.
  - If 3 or more steps failed in a single cycle: marks the plan as failed and triggers full adaptive replan.

**Step Execution (`_execute_step`):**
- Each step runs its goal through the LLM with tool access (up to 6 tool calls per step).
- After the step produces a result, `_verify()` checks the output against the goal using a separate LLM call (the "verifier" prompt).
- The verifier returns a structured `VerifierResult`: status (`PASS`/`FAIL`/`UNCERTAIN`), confidence, issues, evidence, and recommended action (`COMPLETE`/`RETRY`/`REPLAN`/`HUMAN_REVIEW`).
- Steps are retried up to `max_retries` (default 2) on verification failure.
- On `HUMAN_REVIEW` action, the plan is marked with a non-fatal error requiring human intervention.

**Adaptive Replanning (`_adaptive_replan`):**
- When a plan fails after DAG execution, the planner formats all step results and errors into a prompt asking the LLM to produce a corrected plan.
- The new plan replaces the old one and is re-executed.

**Synthesis (`_synthesize`):**
- Combines all step results into a final response using an LLM call with the synthesis prompt.
- Each step is rendered with its goal, status, verification outcome, confidence, and result.

**Plan Scoring (`_score_plan`):**
- Computes a quality score (0.0–1.0) for the generated plan based on step count (ideal 3–8), dependency depth, and tool coverage.
- Purely heuristic; does not use a learned model.

### 4.3 Context Manager (`core/context.py`)

Builds the message list the agent sends to the LLM each turn.

- `build_system_prompt()` — assembles tool schemas as bullet points with parameter details. Injects relevant memories via `MemoryStore.build_context()`.
- `initial_messages()` — returns `[system prompt, user request]`.
- `trim_history()` — keeps the conversation bounded at 24 messages. Always keeps the system prompt and the latest user message.

### 4.4 Task Manager (`core/task_manager.py`)

Long-lived task state machine backed by the `Task` SQLModel table.

- States: `CREATED → RUNNING → COMPLETED / FAILED / CANCELLED / PAUSED`.
- Creates tasks via `create_task()` which generates a UUID public_id and inserts a `Task` row.
- Provides `list_tasks()`, `cancel_task()`, `pause_task()`, `resume_task()`, `delete_task()`.
- Uses sync DB queries directly (not the async tracker) to avoid circular dependencies.
- `get_task()` returns a `TaskInfo` with progress summary including step counts from the `ExecutionStep` table.

### 4.5 Event Bus (`core/events.py`)

In-process async pub/sub.

- `EventBus` manages subscriptions as async iterators. Each subscriber gets an `asyncio.Queue`.
- `publish(event)` — async, awaits all subscribers receiving the event.
- `publish_nowait(event)` — fire-and-forget for non-critical events.
- `subscribe(topic=None)` — returns a `(sub_id, async_iterator)`. `topic=None` subscribes to all events.
- Events have `type`, `topic`, `ts`, `payload`. Topics are typically task public_ids or `"system"`.
- The WebSocket endpoint subscribes to the bus on connect and forwards events to the client.

### 4.6 Execution Tracker (`core/tracker.py`)

Async tracker that records steps, checkpoints, and task progress to the DB during agent execution.

Uses `async_session_scope()` and `select()` style queries. Logs every `ExecutionStep` (LLM calls, tool calls, plan steps) with timestamps, duration, input/output previews, and error details.

### 4.7 Reflection Engine (`core/reflection.py`)

Post-task analysis.

- `ReflectionEngine.reflect()` — loads task timeline from the tracker, formats it as a structured prompt, calls the LLM to analyse the task, and returns a `ReflectionResult` with confidence scores, mistake/improvement counts, and free-form notes.
- `store_reflection_memories()` — stores the reflection analysis as a `ReflectionRecord` in the DB and creates `Memory` records with category `REFLECTION` for learnings that should persist.
- Configuration: enabled/disabled via `security.reflection_enabled`.

---

## 5. Async Runtime

### 5.1 FastAPI

The application runs under `uvicorn` as an ASGI server. `create_app()` in `main.py` builds the `FastAPI` instance with:

- Lifespan handler: initializes logging, DB, event bus, confirmation manager, tool registry, intelligence scheduler, and LLM diagnostics.
- Middleware stack (outermost first): `AuthMiddleware` (bearer token), `RateLimitMiddleware` (120 req/min per IP), `RequestIDMiddleware` (X-Request-ID header), `CORSMiddleware`.

### 5.2 Async Database Sessions

Two engine configurations in `db/base.py`:

- **Async engine** (`sqlite+aiosqlite://`) — used by the agent runtime (tracker, `_set_task_mode`, `_complete`, `_fail`). WAL mode, busy timeout 5s.
- **Sync engine** (`sqlite://`) — used by tools (`ToolInvocation` log), task manager, memory store, security audit, and training/ML code. WAL mode, busy timeout 5s.

Both share the same database file (`veyron.db`). The `async_session_scope()` context manager yields an `AsyncSession` and auto-commits (or rolls back) on exit.

### 5.3 Background Tasks

- Agent runs are dispatched via FastAPI's `BackgroundTasks` (runs in the same event loop, not a thread pool).
- The intelligence scheduler runs as a long-lived `asyncio.Task` started during lifespan.
- Training is spawned as a subprocess (via `asyncio.create_subprocess_exec`) to avoid blocking the event loop.
- Reflection runs as `asyncio.create_task` in the background.

### 5.4 Event Loop Considerations

- The agent's `_generate()` method is fully async — `generate_stream()` yields chunks as they arrive from the HTTP stream to Ollama.
- Tool execution (`tool.safe_run()`) uses `asyncio.wait_for` for configurable timeouts.
- The confirmation manager awaits user response on an `asyncio.Future` with a configurable timeout (default 120s).
- All tracker DB writes use `AsyncSession` and `await`.

---

## 6. Memory System

### 6.1 Architecture

Memory is backed entirely by SQLite, not a vector database. There is no ChromaDB connection in the deployed code. The `chromadb` package is listed as an optional dependency (`vector` extras) for future use.

The `MemoryStore` (`memory/store.py`) provides the full API:

| Method | Description |
|--------|-------------|
| `store()` | Create a memory with category, content, importance, tags |
| `get()` | Retrieve by public_id |
| `update()` | Modify content, importance, tags |
| `delete()` | Remove permanently |
| `search()` | Two-stage retrieval: SQL filter + heuristic score + optional model reranker |
| `recall()` | Mark as recalled, update quality scores |
| `recent()` | Most recently created |
| `important()` | Above-threshold importance |
| `build_context()` | Format top memories for system prompt injection |
| `find_similar_memories()` | Similarity via `SequenceMatcher` ratio |
| `merge_similar_memories()` | Auto-merge candidates via `MemoryMerger` |

### 6.2 Search Pipeline (`store.py:search`)

1. **Candidate retrieval** — SQL query with `ilike` keyword match, optional category/tag filters, ordered by importance descending. Candidate pool = `max(limit * 4, 20)`.
2. **Heuristic scoring** — each candidate receives a composite score:
   - `importance * 0.4 + usefulness * 0.3 + reliability * 0.3`
   - Keyword match count bonus (`+0.05` per occurrence)
   - Recency bonus (created within 1h: `+0.2`, within 24h: `+0.1`)
   - Recall frequency bonus (capped at `+0.1`)
3. **Optional reranker** — if the `memory_retrieval` scikit-learn model is loaded and fitted, its `predict()` method reranks the top candidates. Falls back to heuristic ordering.
4. **Truncation** — returns top `limit` results.

### 6.3 Importance Scoring (`memory/importance.py`)

Heuristic keyword-based scorer (not a learned model). Scans for high-importance keywords (security, password, config, architecture, etc.) and medium-importance keywords (preference, setting, workflow, etc.). Adds length and recall-count bonuses.

### 6.4 Lifecycle (`memory/lifecycle.py`)

- **Decay** — exponential: `I' = I * 0.5^(days_since_recall / half_life)` (default half-life 30 days). When importance falls below `MIN_IMPORTANCE` (0.05), the memory is marked `decayed = True`.
- **Duplicate detection** — exact content hash (SHA-256 of trimmed lowercase content).
- **Merge** — `merge_memories()` combines importance (max), tags (union), and recall counts. Deletes secondary memories. `MemoryMerger` finds candidates via `SequenceMatcher` ratio >= 0.75.

### 6.5 Quality Scoring (`memory/scoring.py`)

Each memory has three quality scores:

| Score | Computation |
|-------|-------------|
| **Usefulness** | `importance * 0.5 + recall_freq * 0.3 + recency * 0.2` |
| **Reliability** | Based on recalls-per-day ratio (capped at 1.0). New memories start at 0.3. |
| **Success frequency** | `0.5 + usefulness * 0.5` (proxy; no direct success tracking) |

Overall = usefulness * 0.4 + reliability * 0.3 + success_frequency * 0.3.

### 6.6 User Profile (`memory/user_profile.py`)

Generated from all non-decayed memories. Extracts:
- Preferences (content matching "prefer", "like", "favorite", etc.)
- Frequent actions (matching "run", "build", "deploy", etc.)
- Common tools (matching "tool", "command", "script", etc.)
- Known projects (matching "project", "repo", "repository", etc.)
- Skill patterns (memories with category SKILL)

Profile is cached as a `PROFILE` category memory with importance 0.9.

---

## 7. Intelligence Layer (Micro-Models)

### 7.1 Model Registry (`intelligence/models/registry.py`)

The `ModelRegistry` manages model lifecycle via a JSON file (`model_registry.json`):

- `register(metadata)` — adds a new model entry.
- `promote(model_type, version)` — sets the model as production; previous production is implicitly set to `deprecated`.
- `rollback(model_type, version)` — reverts a previous candidate to production, deprecating the current production.
- `get_production(model_type)` — returns the current production model metadata.
- `list_models()` — returns all registered models.

A parallel `ModelVersion` SQLModel table stores version history for programmatic queries.

### 7.2 Micro-Model Inventory

All models are scikit-learn `Pipeline` objects (typically `TfidfVectorizer + LogisticRegression`) serialized via pickle. Each sub-package follows the same structure: `dataset.py`, `model.py`, `trainer.py`, `inference.py`.

| Model | Package | Purpose | Input | Output | Training Data |
|-------|---------|---------|-------|--------|---------------|
| **Intent Router** | `intent_router/` | Classifies request intent | Request text | Intent category + confidence | Synthetic + real corrections + LLM-generated |
| **Tool Selector** | `tool_selector/` | Predicts relevant tools | Request text | Tool names with scores | Synthetic + real corrections + LLM-generated |
| **Planning Model** | `planning/` | Predicts if request needs planning | Request text + intent category | `requires_plan` bool + `estimated_steps` + confidence | Synthetic |
| **Memory Retrieval** | `memory_retrieval/` | Reranks memory search results | Query + candidate texts | Ranked indices | Synthetic |
| **Error Recovery** | `error_recovery/` | Classifies error patterns | Error text + context | Error category + recovery strategy | Synthetic |

### 7.3 Training Pipeline (`intelligence/training/run_training.py`)

Entry point: `run_training()`.

1. **Dataset loading** — loads synthetic data from `data/training/synthetic_training_data.jsonl`, merges real corrections from `PredictionLog` (human-corrected predictions), merges LLM-generated data from `data/training/llm_generated_intents.jsonl`.
2. **Deduplication** — by content hash across all sources.
3. **MLflow setup** — sets tracking URI to `sqlite:///mlflow.db`, creates/uses `veyron_intelligence` experiment.
4. **Intent classifier training** — via `TrainingPipelineV2.train_intent()`. Logs params (dataset hash, version, seed) and metrics (accuracy, macro_precision, macro_recall, macro_f1, avg_confidence).
5. **Tool selector training** — via `TrainingPipelineV2.train_tool_selector()`. Logs params and metrics (precision@1, precision@3, recall@1, recall@3, f1@3, exact_match_rate).
6. **Auto-promotion** — compares new model vs current production on the primary metric. Promotion gate: `new_score > current_score + improvement_threshold` (default +0.01). Primary metrics: `macro_f1` (intent), `precision_at_1` (tool_selector).
7. **Artifacts** — saves `.pkl` model files, evaluation reports (JSON), training metadata JSON, VERSION file.

### 7.4 Inference and Runtime Integration

**Intent Router** (`core/intelligence.py:classify_request`):
1. Loads the production intent classifier and tool selector from the Model Registry.
2. Calls `intent_router.inference.predict(request)` → gets category + confidence.
3. Calls `tool_selector.inference.predict(request)` → gets predicted tool list.
4. Returns `Intent(mode, domain, confidence, predicted_tools, intent_category)`.
5. Falls back to heuristic classification if models are unavailable or disabled.

**Tool Filtering** (`agent.py:_run_react`):
- If `filter_tools_by_prediction` is enabled and `intent.predicted_tools` is non-empty, only schemas for predicted tools are included in the LLM prompt.
- Reduces token consumption by 50–80% in typical usage.

**Observability** (`intelligence/observability.py`):
- `log_prediction()` writes every inference to the `PredictionLog` table with model name, version, input, output, confidence, latency, and a `needs_review` flag (set when confidence < 0.6).
- `resolve_model_version()` caches the production version string from the registry.

### 7.5 Active Learning

- Every agent interaction is saved to a daily JSONL file via `save_user_interaction()`.
- Supports `feedback_score` (0.0–1.0) submitted via `POST /api/agent/{id}/feedback`.
- When feedback score < 0.5, the related `PredictionLog` records are flagged for review.
- The `IntellegenceScheduler` periodically checks dataset growth. If the user interaction dataset has grown by > `retrain_min_growth_pct` (default 10%) since the last training, it spawns a subprocess to retrain all models.
- The retrain subprocess (`subprocess_train.py`) loads interactions, converts them to `TrainingExample` objects, and runs the same pipeline as `run_training()`.

---

## 8. MLflow Integration

- Tracking URI: `sqlite:///mlflow.db` (local SQLite file).
- Experiment: `veyron_intelligence`.
- Each training run creates two MLflow runs (intent classifier + tool selector) under the same experiment.
- Logged parameters: model_type, model_version, seed, dataset_hash, dataset_md5, dataset_size, corrections count, category count.
- Logged metrics (intent): accuracy, macro_precision, macro_recall, macro_f1, avg_confidence.
- Logged metrics (tool selector): precision_at_1/3, recall_at_1/3, f1_at_3, exact_match_rate.
- Promotion decisions are logged as custom metrics (`promoted_to_production`, `current_macro_f1`, `new_macro_f1`, `macro_f1_improvement`, etc.).
- Model `.pkl` files are logged as MLflow artifacts under the `model/` artifact path.

---

## 9. Database

### 9.1 Schema

SQLite via SQLAlchemy + SQLModel. Schema created by `init_db()` on startup.

**`Task`** — agent task lifecycle:
- `public_id` (str, unique, indexed) — client-facing UUID.
- `status` — enum: created, planning, running, paused, verifying, completed, failed, cancelled.
- `mode` — "react" or "plan".
- Fields for result, error, timestamps, checkpoint data, model used, tool/retry/step counts.

**`Memory`** — long-term memory:
- `public_id` (str, unique, indexed), `category` (enum), `content`, `importance` (float 0–1).
- Quality scores: `usefulness_score`, `reliability_score`, `success_frequency_score`.
- `embedding_id` — reserved for future vector integration (always NULL currently).
- `decayed` (bool) — set by lifecycle maintenance.
- `content_hash`, `source_task`, `tags`, `recall_count`, timestamps.

**`AuditEvent`** — append-only security trail (also mirrored to file-based audit log).

**`ToolInvocation`** — one row per tool call with inputs, result, duration, error.

**`ExecutionStep`** — one row per step within a task (LLM call, tool call, plan step, verification, synthesis). Includes step_index, step_type, name, status, timestamps, duration, input/output previews, retry_count.

**`EvaluationMetric`**, **`ReflectionRecord`** — task evaluation and reflection analytics.

**`Workflow`**, **`WorkflowStepModel`** — reusable workflow definitions.

**`Skill`** — learned skills from execution pattern detection.

**`PluginRegistration`** — persisted plugin metadata.

**`LearningEvent`** — audit trail for learning system.

**`BenchmarkRun`** — benchmark execution records.

**`ModelVersion`** — version history for trained models.

**`PredictionLog`** — observability records for ML predictions. Includes `needs_review` and `user_correction` fields.

### 9.2 Migration Strategy

No migration tooling. Schema changes are additive: `init_db()` calls `SQLModel.metadata.create_all()` which is a no-op for existing tables. Columns added after initial deployment will be created automatically when the application starts, as long as they have nullable defaults.

---

## 10. Tool System

### 10.1 Tool Interface (`tools/base.py`)

```python
class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    permission: ClassVar[PermissionLevel]  # FREE | CONFIRM | RESTRICTED
    Inputs: ClassVar[type[BaseModel]]      # Pydantic input schema
    max_retries: ClassVar[int]
    retry_delay_ms: ClassVar[int]
    timeout_ms: ClassVar[int]

    async def run(self, ctx: ToolContext, **inputs) -> ToolResult: ...
    async def safe_run(self, ctx, **inputs) -> ToolResult: ...
    @classmethod
    def schema_for_llm(cls) -> dict: ...
```

`safe_run()` is the caller-facing entry point:
1. Validates inputs against the Pydantic schema.
2. Evaluates safety policy (risk classification + permission check).
3. If CONFIRM or RESTRICTED: calls confirmation flow.
4. Executes `run()` with retry and timeout.
5. Returns `ToolResult(ok, output, data, error, duration_ms)`.

### 10.2 Registry (`tools/registry.py`)

`ToolRegistry` auto-discovers all `Tool` subclasses via `pkgutil.iter_modules` on the `veyron.tools` package. Modules `base`, `registry`, and `__init__` are skipped.

Lazy-initialized on first use (thread-safe with `threading.Lock`).

### 10.3 Tools Implemented

| Tool | Permission | Purpose |
|------|-----------|---------|
| `filesystem_read` | FREE | Read files, list directories, stat paths within sandbox roots |
| `system_monitor` | FREE | CPU, RAM, disk, processes, health via psutil |
| `terminal` | CONFIRM | Shell execution with per-command classification |
| `project_analyzer` | FREE | Technology detection, dependency parsing, issue analysis |

### 10.4 Execution Security

All tools pass through `SafetyPolicy.evaluate()` before execution. The policy:
1. Classifies risk level (LOW/MEDIUM/HIGH/CRITICAL) using tool defaults + operation keywords.
2. Applies approval mode (AUTONOMOUS/CONFIRM/SAFE).
3. Returns `(allowed, reason)`. Reason starts with `"confirm:"` if user approval is needed.

The `terminal` tool adds per-command classification: `classify_command()` parses the shell command via `shlex`, checks a static allowlist (`ls`, `cat`, `git status`, etc.), checks a denylist (`rm -rf`, `shutdown`, `sudo`, etc.), detects shell metacharacters (`;`, `|`, `&&`, etc.), and returns the appropriate permission level.

---

## 11. Workflow Engine (`workflow/engine.py`)

Reusable, multi-step definitions.

**`WorkflowDefinition`** — name, description, version, tags, variable names, list of `WorkflowStep`.

**`WorkflowStep`** — step_type (tool_call / wait / llm_call / condition / sub_workflow), tool_name, params (with `$variable` template substitution), condition expression, retry_count, retry_delay_ms, failure_policy (abort / skip / ignore), timeout_ms.

**Execution**:
1. Variables are resolved via `string.Template.safe_substitute()` before each step.
2. Conditions are evaluated as simple equality/inequality expressions.
3. Steps execute sequentially. On failure, retry up to `retry_count` times.
4. After retries are exhausted, the failure_policy determines behavior: `abort` (return error), `skip` (continue), `ignore` (continue and mark failed).

**Persistence**: `WorkflowRegistry` stores definitions in the `Workflow` + `WorkflowStepModel` tables.

---

## 12. Plugin SDK (`plugin/sdk.py`)

`PluginBase` abstract class with lifecycle:
- `initialize()` — called on load. Return False to abort loading.
- `shutdown()` — called on unload.
- `register_tool()`, `register_command()`, `register_workflow()` — registration helpers.

`PluginManifest` — name, version, description, author, entry_point, min_veyron_version.

`PluginRegistry` discovers plugins from the `plugins/` directory (both directory-based (`plugin_name/__init__.py`) and single-file (`plugin_name.py`)). Calls `importlib.util.spec_from_file_location` to load modules, searches for `PluginBase` subclasses, and instantiates them.

Plugin tools are aggregated by `get_tools_from_plugins()` and could be registered into the tool registry, but the current `main.py` does not wire this in during startup.

---

## 13. Security

### 13.1 Path Policy (`security/path_policy.py`)

- Validates all filesystem paths against configured sandbox roots.
- Decodes URL-encoded path characters (prevents `..` smuggling).
- Resolves symlinks (`resolve(strict=True)`) before checking containment.
- Returns a resolved `Path` on success; raises `PathPolicyError` on failure.

### 13.2 Command Policy (`security/command_policy.py`)

- `classify_command(command)` → `FREE` / `CONFIRM` / `RESTRICTED`.
- FREE allowlist: read-only commands (`ls`, `cat`, `git status`, `ps`, `node --version`, etc.).
- RESTRICTED keywords: destructive commands (`rm`, `format`, `shutdown`, `sudo`, `kill -9`, `del`, etc.).
- Shell metacharacters (`;`, `|`, `&&`, `>`, backtick) in any command downgrade it to CONFIRM minimum.
- Input length capped at 4096 characters to prevent DoS.

### 13.3 Confirmation Flow (`security/confirmations.py`)

- `ConfirmationManager.request()` creates a `PendingConfirmation`, publishes a `security.confirm` event on the bus, and awaits an `asyncio.Future` (120s timeout → auto-deny).
- `respond()` resolves the pending confirmation. RESTRICTED actions require a `reason` string.
- Protected against unbounded growth (max 100 pending confirmations).

### 13.4 Audit Log (`security/audit.py`)

- Append-only daily JSONL files: `data/audit/audit-YYYY-MM-DD.jsonl`.
- Thread-safe writes via `threading.Lock`.
- Every privileged action is recorded: action, subject, permission, inputs, outcome, reason, detail, timestamp.

### 13.5 API Authentication (`api/auth.py`, `api/middleware.py`)

- `AuthMiddleware` checks `Authorization: Bearer <token>` against the configured `api_auth_token`.
- When `api_auth_token` is `None` (default), all requests pass unauthenticated (dev mode).
- `/api/health` and `/api/info` are exempt from auth.
- Uses `hmac.compare_digest` for constant-time token comparison.

---

## 14. API

### 14.1 REST Endpoints

Base path: `/api/`. OpenAPI docs at `/docs`.

| Path | Module | Description |
|------|--------|-------------|
| `/agent` | `routes/agent.py` | CRUD for agent tasks |
| `/system` | `routes/system.py` | System health and overview |
| `/tools` | `routes/tools.py` | Tool listing and schemas |
| `/projects` | `routes/projects.py` | Project analysis |
| `/memory` | `routes/memory.py` | Memory CRUD and search |
| `/dashboard` | `routes/dashboard.py` | Dashboard metrics |
| `/intelligence` | `routes/intelligence.py` | Micro-model metrics |
| `/learning` | `routes/learning.py` | Skills and learning |

### 14.2 WebSocket (`api/websocket.py`)

- Path: `/ws`.
- On connect: subscribes to ALL events on the bus.
- Client messages: `subscribe` (topic), `unsubscribe` (topic), `confirm.respond` (confirmation_id, approved, reason).
- Server pushes events as JSON: `{type, topic, ts, payload}`.

### 14.3 Event Model

All events published on the bus are forwarded to WebSocket clients. Key event types:

```
task.created    task.started       task.intent       task.completed
task.failed     task.paused        task.cancelled
agent.iteration  agent.thinking    agent.answer      agent.exhausted
tool.request     tool.result
plan.start       plan.created      plan.step.start   plan.step.complete
plan.step.error  plan.step.failed  plan.step.tool    plan.replanned
plan.synthesized
security.confirm security.confirm.resolved
```

---

## 15. Cross-Cutting Concerns

### 15.1 Configuration

`config.py` defines a three-level configuration hierarchy:

```
SecurityConfig → sandbox_roots, approval_mode, confirm_timeout_seconds, agent_max_iterations, ...
ModelConfig    → ollama_url, base_model, temperature, max_tokens, remote_enabled, ...
ServerConfig   → host, port, cors_origins, frontend_dist, api_auth_token
```

Loading order (highest precedence first):
1. Environment variables (`VEYRON_*`, `__` for nesting, e.g. `VEYRON_SERVER__HOST`)
2. `.env` file
3. `config.yaml`
4. Built-in defaults

### 15.2 Logging

- Python's `logging` module with `RotatingFileHandler` (2MB per file, 3 backups).
- Log file: `data/logs/veyron.log`.
- Format: `%(asctime)s %(levelname)s %(name)s: %(message)s`.

### 15.3 Error Handling

- Tools return `ToolResult(ok=False, error=...)` — never raise exceptions to the agent.
- LLM calls that fail are caught and wrapped as `LLMUnavailableError`, which terminates the current run gracefully.
- API errors use standard HTTPException with typed error responses.
- The agent's `run()` wraps the entire execution in a 300-second wall-clock timeout.

### 15.4 Testing

- pytest with `pytest-asyncio` (auto mode).
- Test files in `tests/unit/` (40+ test files covering all subsystems).
- Integration tests in `tests/integration/`.
- Quality benchmarks in `tests/benchmarks/` (learning progress, memory quality, reflection quality, skill detection, workflow prediction).
- Test helpers: `reset_settings_cache()`, `reset_registry()`, `reset_sync_engine()`, `reset_safety_policy()`, etc.
