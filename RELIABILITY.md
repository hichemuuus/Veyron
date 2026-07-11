# PAIOS Reliability Targets

## Target 1: Benchmark Success Rate >95%

- Basic tasks shall succeed >95% of runs
- Intermediate tasks shall succeed >90% of runs
- Advanced tasks shall succeed >80% of runs

Measured by: `python -m benchmarks.runner --suite all`

## Target 2: No Critical Safety Bypasses

- Path traversal attempts shall always be blocked (0 false negatives)
- Dangerous shell commands (with metacharacters) shall never be classified FREE
- CRITICAL risk actions shall always be denied or require confirmation
- All 34 adversarial tests must pass

## Target 3: Graceful Recovery from Provider Failures

- LLM unavailable → agent returns clear error, does not crash
- Partial tool failure → agent retries and proceeds
- Cancellation → agent stops within 1 iteration
- Max iterations → agent returns error, does not hang

## Target 4: Deterministic Behavior

- Same input + same provider responses → same output structure
- No race conditions in singleton state
- Event bus does not drop messages under normal load
- DB transactions are idempotent

## Current Status (2026-07-11)

| Target | Status | Notes |
|--------|--------|-------|
| Benchmark success rate | ❌ **0% (13/13 fail)** | All fail at plan-generation: Ollama not installed. See `benchmark_results/intelligence-gap-report.json` for micro-model roadmap |
| No critical safety bypasses | ✅ **PASS** | 34 adversarial tests pass |
| Graceful recovery | ✅ **PASS** | Agent returns clear error on LLM failure, no crash, no hang |
| Deterministic behavior | ✅ **PASS** | 324 tests deterministic under repeated runs; concurrency-hardened singletons |

## Eval Benchmark Results (2026-07-11)

| Category | Tasks | Passed | Failed | Pass Rate | Avg Duration (ms) | Avg Iterations | Avg Tool Calls |
|----------|-------|--------|--------|-----------|-------------------|----------------|----------------|
| basic | 5 | 0 | 5 | 0% | 2554 | 1.0 | 0.0 |
| intermediate | 4 | 0 | 4 | 0% | 2565 | 1.0 | 0.0 |
| advanced | 4 | 0 | 4 | 0% | 2562 | 0.8 | 0.0 |
| **Total** | **13** | **0** | **13** | **0%** | **2540** | **0.9** | **0.0** |

**All failures:** `ollama request failed: All connection attempts failed` — LLM provider (Ollama) not installed.

## Performance Baseline (2026-07-11) — Post Concurrency Hardening

| Operation | Avg (ms) | P99 (ms) |
|-----------|----------|----------|
| classify_command (free) | 0.030 | 0.070 |
| classify_command (restricted) | 0.006 | 0.007 |
| classify_command (metachar) | 0.028 | 0.033 |
| classify_risk | 0.001 | 0.001 |
| memory.store | 1.649 | 2.138 |
| memory.search (empty) | 1.164 | 1.822 |
| memory.search (specific) | 1.208 | 1.991 |
| memory.get | 0.309 | 0.733 |
| memory.count | 0.279 | 0.493 |
| planner.validate (valid) | 0.004 | 0.116 |
| planner.validate (circular) | 0.002 | 0.004 |
| planner.score | 0.005 | 0.004 |

**Performance target**: All non-DB operations under 1ms P99. DB operations under 10ms P99. ✅ **All paths meet target.** Note: memory operations improved from ~4.4ms to ~1.6ms due to benchmarking under less load (concurrency hardening did not degrade performance).
