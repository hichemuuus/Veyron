# Testing

## Test Architecture

- **Framework**: pytest with auto-asyncio mode
- **Organization**: `unit/`, `integration/`, `benchmarks/`
- **Test count**: 882+ tests, 1 skipped (Windows symlink)

## Running Tests

```bash
# Full suite
cd veyron
$env:PYTHONPATH="backend"
pytest

# Specific categories
pytest tests/unit/
pytest tests/integration/
pytest tests/benchmarks/

# With coverage
pytest --cov=veyron

# Specific test file
pytest tests/unit/test_intent_classifier.py -v
```

## Test Infrastructure

- `conftest.py` provides: isolated data dir, sandbox root, singleton resets, fresh SQLite DB, stub LLM provider
- All singletons reset between tests (engine, registry, bus, manager, provider, agent, task_manager, monitor)
- `StubProvider` yields deterministic responses for agent tests (no LLM dependency)
- Auto-asyncio mode for async test support

## Test Coverage by Area

| Area | Test Count | Key Files | Quality |
|------|-----------|-----------|---------|
| Security | ~70+ | test_path_policy, test_command_policy, test_safety, test_audit, test_adversarial | Robust |
| Tools | ~50+ | test_filesystem, test_terminal, test_monitor, test_project_analyzer, test_registry | Solid |
| Agent | ~80+ | test_react, test_planner, test_context, test_reflection, test_evaluator | Comprehensive |
| Memory | ~23 | test_crud, test_search, test_lifecycle, test_scoring | Thorough |
| Intelligence | ~80+ | test_intent, test_tool_selector, test_models, test_training_pipeline | Extensive |
| Training Pipeline | ~80+ | test_collector, test_dataset, test_quality, test_exporter, test_v2 | Deep |
| Integration | ~15 | test_e2e_agent_loop, test_process_pipeline | Coverage |
| Benchmarks | ~30 | test_learning, test_memory, test_reflection, test_skill, test_workflow | Measured |
| Events/WS/Task/Dashboard | ~40+ | test_events, test_websocket, test_task_manager, test_dashboard, test_history | Broad |
| Adversarial | 34 | test_adversarial | Targeted |

## CI Integration

- GitHub Actions workflow in `.github/workflows/release.yml`
- Tests run as part of the release pipeline

## Writing Tests

- Use `StubProvider` for agent tests
- Use `fresh_db` fixture for DB tests
- Use `isolated_data_dir` (auto-applied) for file system isolation
- Follow existing patterns in test files
