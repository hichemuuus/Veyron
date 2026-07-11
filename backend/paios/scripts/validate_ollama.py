"""Ollama integration validation script.

Validates the LLM provider configuration, connectivity, and basic
functionality. Run with:

    $env:PYTHONPATH="backend"; python -m paios.scripts.validate_ollama

Exits with code 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

logger = logging.getLogger(__name__)


def _check_ollama_installed() -> bool:
    """Check if the ollama CLI is available on the PATH."""
    import shutil

    if shutil.which("ollama") is not None:
        logger.info("ollama CLI found on PATH")
        return True
    logger.warning("ollama CLI not found on PATH")
    return False


async def _check_ollama_running(url: str) -> bool:
    """Check if the Ollama server is reachable."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                logger.info("Ollama server reachable at %s (%d models found)", url, len(models))
                for m in models:
                    logger.info("  available model: %s", m.get("name", "unknown"))
                return True
            logger.warning("Ollama server returned status %d", resp.status_code)
            return False
    except httpx.ConnectError:
        logger.warning("Cannot connect to Ollama at %s", url)
        return False
    except Exception as e:
        logger.warning("Ollama connectivity check failed: %s", e)
        return False


async def _check_model_available(url: str, model: str) -> bool:
    """Check that the configured model is pulled."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{url}/api/tags")
            if resp.status_code != 200:
                return False
            models = resp.json().get("models", [])
            for m in models:
                if model in m.get("name", ""):
                    logger.info("model '%s' is available", model)
                    return True
            logger.warning("model '%s' not found in Ollama. Pull it with: ollama pull %s", model, model)
            return False
    except Exception as e:
        logger.warning("model check failed: %s", e)
        return False


async def _test_basic_generation(url: str, model: str) -> bool:
    """Send a simple prompt and verify a non-empty response."""
    import httpx

    logger.info("testing basic generation with model '%s'...", model)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Say 'hello' in one word."}],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 50},
                },
            )
            if resp.status_code != 200:
                logger.warning("generation request failed: HTTP %d", resp.status_code)
                return False
            message = resp.json().get("message", {})
            content = message.get("content", "")
            if content.strip():
                logger.info("basic generation OK (got %d chars)", len(content.strip()))
                return True
            logger.warning("generation returned empty content")
            return False
    except Exception as e:
        logger.warning("basic generation failed: %s", e)
        return False


async def _test_tool_calling(url: str, model: str) -> bool:
    """Test that the model can produce tool call JSON."""
    import httpx

    logger.info("testing tool-calling capability with model '%s'...", model)
    functions = [
        {
            "name": "get_weather",
            "description": "Get the weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location"],
            },
        }
    ]
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "What is the weather in London?"}],
                    "stream": False,
                    "tools": functions,
                    "options": {"temperature": 0.1, "num_predict": 256},
                },
            )
            if resp.status_code != 200:
                logger.warning("tool-call request failed: HTTP %d", resp.status_code)
                return False
            message = resp.json().get("message", {})
            has_tool_calls = "tool_calls" in message and message["tool_calls"]
            if has_tool_calls:
                logger.info("tool-calling OK (model produced tool call)")
                return True
            logger.warning("tool-calling: model did not produce a tool call")
            return False
    except Exception as e:
        logger.warning("tool-calling test failed: %s", e)
        return False


async def _test_embedding(url: str, model: str) -> bool:
    """Test the embedding endpoint."""
    import httpx

    logger.info("testing embeddings with model '%s'...", model)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{url}/api/embed",
                json={"model": model, "input": "test sentence for embedding"},
            )
            if resp.status_code != 200:
                logger.warning("embedding request failed: HTTP %d", resp.status_code)
                return False
            data = resp.json()
            embeddings = data.get("embeddings", [])
            if embeddings and len(embeddings[0]) > 0:
                logger.info("embeddings OK (dimension=%d)", len(embeddings[0]))
                return True
            logger.warning("embedding returned empty result")
            return False
    except Exception as e:
        logger.warning("embedding test failed: %s", e)
        return False


async def _measure_latency(url: str, model: str, n: int = 3) -> dict:
    """Measure average generation latency."""
    import httpx

    logger.info("measuring generation latency (%d samples)...", n)
    times: list[float] = []
    for i in range(n):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                start = time.monotonic()
                resp = await client.post(
                    f"{url}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Count from 1 to 5."}],
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 50},
                    },
                )
                elapsed = time.monotonic() - start
                if resp.status_code == 200:
                    times.append(elapsed)
                    logger.info("  sample %d: %.2fs", i + 1, elapsed)
        except Exception:
            pass
    avg = sum(times) / len(times) if times else 0.0
    logger.info("average latency: %.2fs (over %d samples)", avg, len(times))
    return {"avg_seconds": avg, "samples": len(times), "raw_times": times}


async def run_validation(url: str | None = None, model: str | None = None) -> dict:
    """Run all validation checks and return a results dict."""
    from paios.config import get_settings

    settings = get_settings()
    base_url = url or settings.model.ollama_url
    model_name = model or settings.model.base_model

    results: dict[str, bool | dict] = {}

    results["ollama_cli"] = _check_ollama_installed()
    results["ollama_running"] = await _check_ollama_running(base_url)

    if results.get("ollama_running"):
        results["model_available"] = await _check_model_available(base_url, model_name)
        if results.get("model_available"):
            results["basic_generation"] = await _test_basic_generation(base_url, model_name)
            results["tool_calling"] = await _test_tool_calling(base_url, model_name)
            results["embedding"] = await _test_embedding(base_url, model_name)
            results["latency"] = await _measure_latency(base_url, model_name)
        else:
            results["basic_generation"] = False
            results["tool_calling"] = False
            results["embedding"] = False
            results["latency"] = {"avg_seconds": 0.0, "samples": 0}
    else:
        results["model_available"] = False
        results["basic_generation"] = False
        results["tool_calling"] = False
        results["embedding"] = False
        results["latency"] = {"avg_seconds": 0.0, "samples": 0}

    return results


def _interpret(results: dict) -> str:
    """Return a human-readable summary."""
    lines = ["\n=== OLLAMA VALIDATION REPORT ==="]
    checks = ["ollama_cli", "ollama_running", "model_available", "basic_generation", "tool_calling", "embedding"]
    all_ok = all(results.get(c) for c in checks)

    for key in checks:
        status = results.get(key, False)
        symbol = "PASS" if status else "FAIL"
        lines.append(f"  [{symbol}] {key}")

    lat = results.get("latency", {})
    if isinstance(lat, dict) and lat.get("samples", 0) > 0:
        lines.append(f"  [INFO] latency: {lat['avg_seconds']:.2f}s avg ({lat['samples']} samples)")

    if all_ok:
        lines.append("\n  ALL CHECKS PASSED. Ollama integration is healthy.")
    else:
        if not results.get("ollama_cli"):
            lines.append("\n  Ollama CLI not found. Install from https://ollama.ai")
        if not results.get("ollama_running"):
            lines.append("  Start Ollama: open the Ollama app or run 'ollama serve'")
        if results.get("ollama_running") and not results.get("model_available"):
            model = results.get("_model", "<model>")
            lines.append(f"  Pull model: ollama pull {model}")
        lines.append("\n  Run validations again after resolving issues.")

    return "\n".join(lines)


def main() -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate PAIOS Ollama integration")
    parser.add_argument("--url", help="Ollama server URL (default: from config)")
    parser.add_argument("--model", help="Model name (default: from config)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    results = asyncio.run(run_validation(url=args.url, model=args.model))

    if isinstance(results.get("latency"), dict):
        results["latency"] = results["latency"]

    print(_interpret(results))

    checks = ["ollama_cli", "ollama_running", "model_available", "basic_generation", "tool_calling", "embedding"]
    return 0 if all(results.get(c) for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
