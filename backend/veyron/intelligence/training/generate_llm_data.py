"""Generate diverse intent-classification training data via Ollama.

Usage:
    python -m veyron.intelligence.training.generate_llm_data

Prompts the local Ollama model to generate 50 diverse user queries per
intent category, then writes them to ``data/llm_generated_intents.jsonl``
in a format compatible with :func:`load_jsonl_as_examples`.

When Ollama is unavailable, a template-based fallback generator produces
equivalent data using the same rephrasing pipeline as ``generate_dataset.py``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from pathlib import Path
from typing import Any

from veyron.config import DATA_DIR
from veyron.intelligence.training.preparation.splitter import INTENT_CATEGORIES

logger = logging.getLogger(__name__)

LLM_DATA_PATH = DATA_DIR / "training" / "llm_generated_intents.jsonl"

random.seed(42)

SEED_EXAMPLES: dict[str, list[str]] = {
    "question_answering": [
        "what is the default configuration",
        "how do i install this project",
        "what does this error message mean",
    ],
    "coding_task": [
        "set up eslint configuration",
        "create a websocket handler",
        "refactor the authentication module",
    ],
    "project_analysis": [
        "recommend improvements for this project",
        "analyze the project for potential issues",
        "does the project use environment variables properly",
    ],
    "file_operation": [
        "read the copyright notice",
        "show the test setup file",
        "list all markdown files in the project",
    ],
    "tool_execution": [
        "run linting on the codebase",
        "show commit details for the last commit",
        "check for uncommitted changes",
    ],
    "planning_task": [
        "prepare a release for version 2.0",
        "compare two branches and summarize differences",
        "create a deployment pipeline",
    ],
    "debugging": [
        "why did the process exit with code 1",
        "debug the websocket disconnection",
        "investigate the memory leak in the worker process",
    ],
    "system_management": [
        "how much free disk space is available",
        "find large files over 100MB",
        "how many CPU cores does this machine have",
    ],
    "research": [
        "research the latest trends in machine learning",
        "find best practices for API rate limiting",
        "look up the documentation for FastAPI middleware",
    ],
    "conversation": [
        "that makes sense, thanks",
        "how does this work",
        "can you explain that in simpler terms",
    ],
    "memory_recall": [
        "remember what we discussed about deployments",
        "remind me about the project architecture",
        "recall my preferred code style",
    ],
    "user_preference_update": [
        "change the default terminal width",
        "update my notification settings",
        "remember my choice of dark theme",
    ],
    "context_request": [
        "what have we accomplished so far",
        "show the session overview",
        "give me the context of the current task",
    ],
}


# ── Template-based fallback (used when Ollama is unavailable) ──────────────

REPHRASE_PREFIXES: dict[str, list[str]] = {
    "easy": [
        "{t}",
        "can you {t}",
        "please {t}",
        "could you {t}",
        "i need you to {t}",
        "hey, {t}",
        "{t} please",
        "can i get you to {t}",
    ],
    "moderate": [
        "{t}",
        "can you {t}",
        "could you please {t}",
        "im trying to {t}",
        "id like you to {t}",
        "i need help: {t}",
        "would you {t}",
        "can i get you to {t}",
    ],
    "hard": [
        "{t}",
        "this is complex: {t}",
        "ive been trying to {t} but its not working",
        "i need help with {t}",
        "can you handle {t}",
        "i need you to {t}",
    ],
}

LOCATION_VARIANTS = [
    "",
    " in this project",
    " in the repo",
    " in this directory",
    " across the whole app",
    " in the source code",
    " in the test suite",
    " for the tools module",
    " in the core module",
    " in the config files",
]

PROJECT_SUFFIXES = [
    " for this repo",
    " in the project",
    " in this codebase",
    " for the application",
]


def _rephrase(template: str, difficulty: str) -> str:
    fmt = random.choice(REPHRASE_PREFIXES.get(difficulty, REPHRASE_PREFIXES["easy"]))
    result = fmt.format(t=template)
    if random.random() < 0.15:
        suffix = random.choice(LOCATION_VARIANTS)
        if suffix:
            result += " " + suffix
    if random.random() < 0.08 and difficulty in ("moderate", "hard"):
        if not any(s in result for s in PROJECT_SUFFIXES):
            result += random.choice(PROJECT_SUFFIXES)
    return result.strip()


# Per-intent template seeds (each expanded to ~50 via rephrasing)
_INTENT_TEMPLATES: dict[str, list[tuple[str, list[str], str, bool]]] = {
    "question_answering": [
        ("what is the default configuration", [], "easy", False),
        ("how do i install this project", [], "easy", False),
        ("what does this error mean", [], "easy", False),
        ("explain the architecture overview", [], "moderate", False),
        ("what is the purpose of this module", [], "moderate", False),
        ("how does authentication work here", [], "moderate", False),
        ("what version of python does this require", [], "easy", False),
        ("what are the system requirements", [], "easy", False),
        ("tell me about the project structure", [], "moderate", False),
    ],
    "coding_task": [
        ("set up eslint configuration", ["terminal"], "moderate", False),
        ("create a websocket handler", ["terminal", "filesystem_read"], "hard", True),
        ("refactor the authentication module", ["project_analyzer", "terminal"], "hard", True),
        ("implement input validation", ["terminal", "filesystem_read"], "hard", True),
        ("write unit tests for the api module", ["terminal"], "moderate", False),
        ("add error handling to the database layer", ["terminal", "filesystem_read"], "hard", True),
        ("create a new middleware component", ["terminal"], "moderate", False),
        ("optimize the database queries", ["project_analyzer", "terminal"], "hard", True),
    ],
    "project_analysis": [
        ("recommend improvements for this project", ["project_analyzer"], "moderate", False),
        ("analyze the project for potential issues", ["project_analyzer"], "moderate", False),
        ("does the project use environment variables properly", ["project_analyzer"], "moderate", False),
        ("what is the code quality score", ["project_analyzer"], "moderate", False),
        ("find performance bottlenecks", ["project_analyzer", "system_monitor"], "hard", True),
        ("analyze dependency versions for outdated packages", ["project_analyzer", "terminal"], "moderate", False),
        ("check test coverage across the codebase", ["project_analyzer", "terminal"], "moderate", False),
        ("identify security vulnerabilities", ["project_analyzer"], "hard", False),
    ],
    "file_operation": [
        ("read the readme file", ["filesystem_read"], "easy", False),
        ("list files in the current directory", ["filesystem_read"], "easy", False),
        ("show the test setup file", ["filesystem_read"], "easy", False),
        ("find all markdown files in the project", ["filesystem_read"], "easy", False),
        ("read the database schema file", ["filesystem_read"], "easy", False),
        ("search for the word deprecated in the codebase", ["filesystem_read"], "moderate", False),
        ("show directory tree two levels deep", ["filesystem_read"], "moderate", False),
        ("list all environment files", ["filesystem_read"], "easy", False),
    ],
    "tool_execution": [
        ("run linting on the codebase", ["terminal"], "moderate", False),
        ("show commit details for the last commit", ["terminal"], "easy", False),
        ("check for uncommitted changes", ["terminal"], "easy", False),
        ("run the test suite", ["terminal"], "moderate", False),
        ("install the project dependencies", ["terminal"], "easy", False),
        ("build the docker image", ["terminal"], "moderate", False),
        ("deploy to staging environment", ["terminal"], "hard", True),
        ("format all python files with black", ["terminal"], "moderate", False),
    ],
    "planning_task": [
        ("prepare a release for version 2.0", ["terminal", "filesystem_read"], "hard", True),
        ("compare two branches and summarize differences", ["terminal"], "moderate", False),
        ("create a deployment pipeline", ["terminal", "project_analyzer"], "hard", True),
        ("plan the migration to a new api version", ["terminal", "project_analyzer"], "hard", True),
        ("schedule a backup strategy", ["terminal"], "moderate", False),
        ("set up monitoring and alerting", ["system_monitor", "terminal"], "hard", True),
        ("create a database migration plan", ["filesystem_read", "terminal"], "hard", True),
        ("plan the refactoring of the legacy module", ["project_analyzer", "terminal"], "hard", True),
    ],
    "debugging": [
        ("why did the process exit with code 1", ["terminal", "system_monitor"], "moderate", False),
        ("debug the websocket disconnection", ["filesystem_read", "terminal"], "hard", True),
        ("investigate the memory leak in the worker process", ["system_monitor", "terminal"], "hard", True),
        ("find why the api returns 500 errors", ["filesystem_read", "terminal"], "moderate", False),
        ("debug the slow database query", ["project_analyzer", "terminal"], "hard", True),
        ("trace the source of the null pointer exception", ["filesystem_read"], "moderate", False),
        ("investigate high cpu usage by the application", ["system_monitor", "terminal"], "hard", True),
        ("fix the failing integration test", ["terminal", "filesystem_read"], "moderate", False),
    ],
    "system_management": [
        ("how much free disk space is available", ["system_monitor"], "easy", False),
        ("find large files over 100MB", ["terminal", "filesystem_read"], "moderate", False),
        ("how many CPU cores does this machine have", ["terminal"], "easy", False),
        ("check memory usage", ["system_monitor"], "easy", False),
        ("list running processes", ["system_monitor"], "easy", False),
        ("show system uptime", ["system_monitor"], "easy", False),
        ("run a health check", ["system_monitor"], "easy", False),
        ("check if docker is running", ["terminal"], "easy", False),
    ],
    "research": [
        ("research the latest trends in machine learning", ["terminal"], "moderate", False),
        ("find best practices for API rate limiting", ["terminal"], "moderate", False),
        ("look up documentation for the library version", ["terminal", "filesystem_read"], "moderate", False),
        ("search for open source alternatives", ["terminal"], "moderate", False),
        ("investigate the latest security patches", ["terminal"], "moderate", False),
        ("find benchmark comparisons for database engines", ["terminal"], "hard", False),
        ("research cloud provider pricing", ["terminal"], "moderate", False),
        ("gather information about the latest javascript framework", ["terminal"], "moderate", False),
    ],
    "conversation": [
        ("that makes sense, thanks", [], "easy", False),
        ("how does this work", [], "easy", False),
        ("can you explain that in simpler terms", [], "easy", False),
        ("i understand now, thank you", [], "easy", False),
        ("what do you think about this approach", [], "easy", False),
        ("can you give me an overview", [], "easy", False),
        ("that is a great explanation", [], "easy", False),
        ("i appreciate your help", [], "easy", False),
    ],
    "memory_recall": [
        ("remember what we discussed about deployments", [], "moderate", False),
        ("remind me about the project architecture", [], "moderate", False),
        ("recall my preferred code style", [], "moderate", False),
        ("what did we decide about the logging strategy", [], "moderate", False),
        ("remember that my name is John", [], "easy", False),
        ("do you remember the deployment configuration", [], "moderate", False),
        ("remind me of the meeting notes from yesterday", [], "moderate", False),
        ("save this path for later reference", [], "moderate", False),
    ],
    "user_preference_update": [
        ("change the default terminal width", [], "moderate", False),
        ("update my notification settings", [], "moderate", False),
        ("remember my choice of dark theme", [], "moderate", False),
        ("set my preferred editor to vscode", [], "easy", False),
        ("change the output format to json", [], "moderate", False),
        ("update my working hours preference", [], "moderate", False),
        ("save my default branch name as main", [], "easy", False),
        ("configure my preferred language", [], "easy", False),
    ],
    "context_request": [
        ("what have we accomplished so far", [], "easy", False),
        ("show the session overview", [], "easy", False),
        ("give me the context of the current task", [], "easy", False),
        ("what are we working on right now", [], "easy", False),
        ("summarize the current project status", [], "moderate", False),
        ("what task was i working on before", [], "easy", False),
        ("show the progress of the current operation", [], "easy", False),
        ("remind me what we were doing", [], "easy", False),
    ],
}


def _fallback_generate(target_per_intent: int = 50) -> list[dict[str, Any]]:
    """Generate synthetic data using template rephrasing when Ollama is unavailable."""
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for intent in INTENT_CATEGORIES:
        templates = _INTENT_TEMPLATES.get(intent, [])
        if not templates:
            logger.warning("  No templates for intent '%s', skipping", intent)
            continue

        attempts = 0
        while len([r for r in records if r["intent"] == intent]) < target_per_intent and attempts < 500:
            attempts += 1
            template, tools, difficulty, needs_planning = random.choice(templates)
            request = _rephrase(template, difficulty)

            raw = f"{request}|{'|'.join(sorted(tools))}|{intent}"
            h = hashlib.sha256(raw.encode()).hexdigest()[:16]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            records.append({
                "request": request,
                "intent": intent,
                "expected_tools": sorted(set(tools)),
                "expected_parameters": {},
                "difficulty": difficulty,
                "planning_required": needs_planning,
            })

        count = len([r for r in records if r["intent"] == intent])
        logger.info("  %s: generated %d queries (fallback)", intent, count)

    return records


# ── Ollama generation path ────────────────────────────────────────────────

def _build_prompt(intent: str, examples: list[str]) -> str:
    seed = "\n".join(f"  - {e}" for e in examples)
    return (
        f"Generate 50 diverse, realistic user queries for an AI assistant "
        f"that indicate the intent '{intent}'. "
        f"Examples of this intent:\n{seed}\n"
        f"Output ONLY a JSON array of strings. "
        f"Do not include any other text."
    )


async def _ollama_generate_for_intent(
    intent: str,
    examples: list[str],
    semaphore: asyncio.Semaphore,
) -> list[str]:
    """Generate up to 50 queries for a single intent via Ollama."""
    from veyron.llm.base import GenerateOptions, Message, get_provider

    provider = get_provider()
    prompt = _build_prompt(intent, examples)

    for attempt in range(3):
        try:
            async with semaphore:
                full_text: list[str] = []
                async for chunk in provider.generate_stream(
                    messages=[Message(role="user", content=prompt)],
                    opts=GenerateOptions(temperature=0.7 + attempt * 0.1, max_tokens=4096),
                ):
                    if chunk.text:
                        full_text.append(chunk.text)
            raw = "".join(full_text).strip()

            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("```", 1)[0]
            if raw.startswith("json"):
                raw = raw[4:].strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
                logger.info("  %s: generated %d queries", intent, len(parsed))
                return parsed

            logger.warning("  %s: unexpected response format (attempt %d), retrying", intent, attempt + 1)
        except Exception as e:
            logger.warning("  %s: error on attempt %d: %s", intent, attempt + 1, e)

    logger.error("  %s: failed after 3 attempts", intent)
    return []


async def _ollama_generate_all() -> list[dict[str, Any]]:
    """Attempt to generate data via Ollama for all intents."""
    import asyncio

    semaphore = asyncio.Semaphore(2)
    all_records: list[dict] = []

    for intent in INTENT_CATEGORIES:
        seed = SEED_EXAMPLES.get(intent, SEED_EXAMPLES.get("conversation", []))
        logger.info("Generating for intent '%s' ...", intent)
        queries = await _ollama_generate_for_intent(intent, seed, semaphore)
        for q in queries:
            all_records.append({
                "request": q,
                "intent": intent,
                "expected_tools": [],
                "expected_parameters": {},
                "difficulty": "easy",
                "planning_required": False,
            })

    return all_records


# ── Main ──────────────────────────────────────────────────────────────────

async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.info("Generating LLM training data for %d intents ...", len(INTENT_CATEGORIES))
    logger.info("Output path: %s", LLM_DATA_PATH)

    # Try Ollama first; fall back to template-based generation
    try:
        logger.info("Attempting Ollama connection ...")
        from veyron.llm.base import get_provider
        provider = get_provider()
        available = await provider.is_available()
    except Exception:
        available = False

    if available:
        logger.info("Ollama is available — generating via LLM")
        all_records = await _ollama_generate_all()
    else:
        logger.info("Ollama unavailable — using template-based fallback generator")
        all_records = _fallback_generate(target_per_intent=50)

    LLM_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LLM_DATA_PATH, "w", encoding="utf-8") as f:
        for record in all_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Saved %d records to %s", len(all_records), LLM_DATA_PATH)

    # Print summary
    from collections import Counter
    intent_counts = Counter(r["intent"] for r in all_records)
    logger.info("Per-intent breakdown:")
    for intent in INTENT_CATEGORIES:
        logger.info("  %-25s %3d", intent, intent_counts.get(intent, 0))

    return 0


if __name__ == "__main__":
    import asyncio
    import sys
    sys.exit(asyncio.run(main()))
