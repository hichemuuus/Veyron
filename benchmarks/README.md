# Benchmarks

## Overview
Veyron includes two benchmark frameworks:

1. **Agent Evaluation** (`agent_evaluation/`) — 105 benchmark tasks across 8 categories
2. **Micro-Model Benchmarks** (`benchmarks/intelligence_benchmark.py`) — ML model vs heuristic comparison
3. **Quality Benchmarks** (`tests/benchmarks/`) — 5 pytest benchmark suites

## Running Benchmarks

```bash
# Agent evaluation
cd veyron
$env:PYTHONPATH="backend"
python benchmarks/runner.py --suite all

# Intelligence benchmark
python benchmarks/intelligence_benchmark.py

# Quality benchmarks
pytest tests/benchmarks/
```

## Key Results

### Micro-Model Performance
| Model | Synthetic Accuracy | Real Accuracy | Latency |
|-------|-------------------|---------------|---------|
| Intent Router | 98.51% | ~60% | <10ms |
| Tool Selector | 96.02% | — | <10ms |
| Memory Retrieval | MRR: 0.3972 | — | <50ms |

### Intelligence Latency
- v2 pipeline: 8-9x faster than v1
- Average inference: <10ms per prediction

### Hardware Profiles
- Minimum: 8GB RAM, 4-core CPU, 2GB storage
- Recommended: 16GB RAM, 8-core CPU, SSD
- Ollama model: qwen2.5:3b-instruct (3B parameters)
