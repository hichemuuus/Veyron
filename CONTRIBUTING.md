# Contributing to Veyron

---

## Development Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/veyron.git
cd veyron

# Create a virtual environment (Python 3.11–3.13)
uv venv --python 3.12

# Install all dependencies (including dev and ML extras)
uv pip install -e ".[dev,ml]"

# Launch the API server
uv run uvicorn veyron.main:app --reload
# → http://localhost:8000  (docs at /docs)
```

### Frontend (optional)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Desktop App (optional)

```bash
cd frontend/src-tauri
cargo build --release
```

---

## Repository Standards

### Branch Strategy

- `main` — production-ready. All commits pass tests and linting.
- `feat/*` — feature branches. Squash-merge into `main`.
- `fix/*` — bug fixes.
- `docs/*` — documentation changes only.
- `refactor/*` — code restructuring with no functional change.

### Commit Conventions

Use conventional commits:

```
feat: add memory reranker micro-model
fix: handle null bytes in agent request input
refactor: extract safety policy into separate class
docs: add architecture diagram to ARCHITECTURE.md
test: add planner DAG execution tests
chore: update ruff config to 100 char line length
```

### Code Review Expectations

- Every PR must be reviewed by at least one maintainer.
- The reviewer verifies:
  - Changes match the PR description.
  - Tests cover the new code (or the PR explains why not).
  - No debugging artifacts, commented code, or print statements.
  - Public APIs are typed and documented.
  - Security implications are considered (especially for tools and API routes).
- The author merges after approval. No self-approvals.

---

## Testing Requirements

### Running Tests

```bash
# Run all tests
uv run pytest -q

# Run specific test categories
uv run pytest tests/unit/
uv run pytest tests/integration/
uv run pytest tests/unit/test_planner.py -v

# Run with coverage
uv run pytest --cov=backend/veyron --cov-report=term-missing
```

### Test Conventions

- Tests live in `tests/unit/`, `tests/integration/`, or `tests/benchmarks/`.
- Test files are named `test_<module>.py`.
- Use `pytest-asyncio` (auto mode is enabled in `pyproject.toml`).
- The `conftest.py` provides:
  - `isolated_data_dir` (autouse) — redirects `backend/data` to a temp directory.
  - `sandbox_root` — a writable temp directory used as the only sandbox root.
  - `settings_with_sandbox` (autouse) — forces the sandbox roots setting to only the temp root.
  - `reset_singletons` (autouse) — resets all process-wide singletons between tests.
  - `fresh_db` — initializes an isolated SQLite DB.
  - `StubProvider` — a fake LLM provider for deterministic agent tests. Yields scripted responses.
- All database state is isolated per test.
- Agent tests should use `StubProvider` to avoid real LLM calls.

### Writing Tests

```python
import pytest
from veyron.some_module import SomeClass


class TestSomeFeature:
    async def test_happy_path(self, fresh_db):
        instance = SomeClass()
        result = await instance.method()
        assert result.ok

    def test_error_case(self):
        ...
```

---

## Formatting and Linting

### Python

Ruff is configured in `pyproject.toml`:
- `line-length = 100`
- `target-version = "py311"`
- Lint rules: `E`, `F`, `I`, `UP`, `B`, `SIM`

```bash
# Check formatting and linting
ruff check backend/ tests/ benchmarks/
```

Run linting before every commit. CI will fail if there are violations.

### TypeScript

```bash
cd frontend
npm run typecheck
```

Follow the project's `tsconfig.json` strict mode settings.

### Rust

```bash
cd frontend/src-tauri
cargo fmt --check
cargo clippy
```

---

## How To ...

### Add a Tool

1. Create a file in `backend/veyron/tools/`, e.g. `my_tool.py`.
2. Subclass `Tool` from `veyron.tools.base`:

```python
from typing import Any, ClassVar
from pydantic import BaseModel, Field
from veyron.tools.base import Tool, ToolContext, ToolResult
from veyron.security.command_policy import PermissionLevel

class MyInputs(BaseModel):
    query: str = Field(..., description="The search query")

class MyTool(Tool):
    name: ClassVar[str] = "my_tool"
    description: ClassVar[str] = "Does something useful"
    permission: ClassVar[PermissionLevel] = PermissionLevel.FREE
    Inputs: ClassVar[type[BaseModel]] = MyInputs

    async def run(self, ctx: ToolContext, **inputs: Any) -> ToolResult:
        query = inputs["query"]
        # Do work...
        return ToolResult(output="result text", data={"key": "value"})
```

3. The tool is auto-discovered by `ToolRegistry` on next import. No registration code needed.
4. Write tests in `tests/unit/test_my_tool.py`.
5. Add the tool to the API endpoint listing in `api/routes/tools.py` if it should be listed.

### Add a Workflow

1. Define a `WorkflowDefinition` with a list of `WorkflowStep`.
2. Save it via the `WorkflowRegistry`:

```python
from veyron.workflow.models import WorkflowDefinition, WorkflowStep, StepType
from veyron.workflow.registry import WorkflowRegistry

steps = [
    WorkflowStep(
        step_type=StepType.TOOL_CALL,
        name="check_disk",
        tool_name="system_monitor",
        params={"operation": "disk"},
    ),
    WorkflowStep(
        step_type=StepType.CONDITION,
        name="alert_if_full",
        condition="$disk_usage > 90",
        tool_name="terminal",
        params={"command": 'echo "Disk almost full"'},
    ),
]

wf = WorkflowDefinition(name="disk_check", steps=steps)
registry = WorkflowRegistry()
pid = registry.save(wf)
```

3. Execute via `WorkflowEngine`:

```python
from veyron.workflow.engine import WorkflowEngine
engine = WorkflowEngine()
result = await engine.execute(wf, variables={"disk_usage": 85})
```

### Add a Plugin

1. Create a directory or file under `backend/plugins/`:

```
plugins/
└── my_plugin/
    ├── __init__.py
    └── ...
```

2. Subclass `PluginBase` from `veyron.plugin.sdk`:

```python
from veyron.plugin.sdk import PluginBase, PluginManifest
from veyron.tools.base import Tool

class MyTool(Tool):
    name = "my_plugin_tool"
    ...

class MyPlugin(PluginBase):
    manifest = PluginManifest(
        name="my_plugin",
        version="1.0.0",
        description="Example plugin",
        author="You",
    )

    async def initialize(self) -> bool:
        self.register_tool(MyTool)
        return True
```

3. The plugin is auto-discovered by `PluginRegistry` from the `plugins/` directory.

### Add a Micro-Model

1. Create a new package under `backend/veyron/intelligence/`, e.g. `my_model/`.
2. Implement the standard files:
   - `schema.py` — input/output dataclasses.
   - `dataset.py` — dataset generation or loading.
   - `model.py` — scikit-learn Pipeline definition.
   - `trainer.py` — training function.
   - `inference.py` — inference function (`predict()`).
3. Add training to `run_training.py` (call the trainer and log metrics).
4. Add inference to the appropriate place in the `core/` or `intelligence/` module.
5. Register the model type in `intelligence/models/registry.py`.
6. Write tests in `tests/unit/test_my_model.py`.

### Register a New Model

Models are registered automatically by the training pipeline. To register manually:

```python
from veyron.intelligence.models.registry import ModelRegistry
from veyron.intelligence.models.schema import ModelMetadata

registry = ModelRegistry()
registry.register(ModelMetadata(
    name="intent_classifier",
    version="v2.0.0-20260717_114439",
    model_type="intent_classifier",
    metrics={"macro_f1": 0.9727},
    path="/path/to/model.pkl",
    status="candidate",
))
registry.promote("intent_classifier", "v2.0.0-20260717_114439")
```

### Add Benchmarks

1. Add benchmark files to `tests/benchmarks/` or `benchmarks/`.
2. For intelligence benchmarks, use the framework in `intelligence/training/benchmark_v2.py`.
3. Run with:

```bash
uv run python -m veyron.intelligence.training.run_benchmark
```

### Write Tests

- Use pytest fixtures from `conftest.py` for isolation.
- Use `StubProvider` for agent tests — script the LLM's responses deterministically.
- For memory tests, use `fresh_db` to get an empty database.
- For tool tests, use `sandbox_root` as the only allowed sandbox path.
- For security tests, monkeypatch settings to change approval mode or risk thresholds.

### Update Documentation

- **README.md** — user-facing overview, quick start, feature list, project structure.
- **ARCHITECTURE.md** — deep implementation reference for engineers. Every statement must be derivable from the codebase. Never describe unimplemented features.
- **CONTRIBUTING.md** — this file. Developer setup, conventions, how-to guides.
- **DECISIONS.md** — design decisions and rationale. Update when adding new subsystems or changing existing ones.
- **CHANGELOG.md** — notable changes per release.

When you add a new feature:
1. Update the relevant section in `README.md` (features, project structure, API endpoints).
2. Update `ARCHITECTURE.md` with implementation details.
3. Add how-to instructions to this file if the feature introduces a new extension point.

---

## CI Expectations

Before submitting a PR, ensure:

1. `ruff check backend/ tests/ benchmarks/` passes with no violations.
2. `uv run pytest -q` passes (known pre-existing failures are acceptable if documented).
3. For frontend changes: `cd frontend && npm run typecheck` passes.
4. For desktop changes: `cd frontend/src-tauri && cargo build` succeeds.
5. New features include tests.
6. New public APIs include type annotations.
7. No secrets, keys, or credentials are committed.
