"""PAIOS FastAPI application entrypoint.

Wires together routes, the event bus, DB init, and (in production) serves the
built frontend. Run with:

    uvicorn paios.main:app --reload

or via the console script: paios
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from paios import __version__
from paios.config import get_settings
from paios.db.base import init_db
from paios.core.events import get_bus
from paios.security.confirmations import get_manager

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Rotating-file + stderr logging."""
    from logging.handlers import RotatingFileHandler

    from paios.config import DATA_DIR

    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(log_dir / "paios.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    _configure_logging()
    init_db()
    # Force eager init of singletons so errors surface at startup, not mid-request.
    get_bus()
    get_manager()
    # Touch the registry so tool discovery happens once now.
    from paios.tools.registry import get_registry
    names = get_registry().names()
    logger.info("PAIOS %s started; %d tools registered: %s", __version__, len(names), names)
    # Check whether the LLM is reachable (fatal if require_local_model).
    try:
        from paios.llm.base import check_provider_available

        available = await check_provider_available()
        if available:
            from paios.llm.base import get_provider

            logger.info("LLM provider '%s' available", get_provider().name)
        else:
            logger.warning("LLM provider unavailable; will retry on first request")
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM availability check: %s", e)

    yield

    # Shutdown cleanup.
    bus = get_bus()
    await bus.shutdown()
    logger.info("PAIOS shutdown complete")


def create_app() -> FastAPI:
    """Build the FastAPI app. Used by uvicorn and tests."""
    settings = get_settings()
    app = FastAPI(
        title="PAIOS",
        description="Personal AI Operating System — agent API",
        version=__version__,
        lifespan=lifespan,
    )

    # Middleware: rate limiting, request IDs.
    from paios.api.middleware import RateLimitMiddleware, RequestIDMiddleware

    app.add_middleware(RateLimitMiddleware, max_requests=120, window_seconds=60)
    app.add_middleware(RequestIDMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes.
    from paios.api.routes import agent, dashboard, projects, system, tools
    from paios.api.websocket import router as ws_router

    app.include_router(agent.router)
    app.include_router(system.router)
    app.include_router(tools.router)
    app.include_router(projects.router)
    app.include_router(dashboard.router)
    app.include_router(ws_router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__, "environment": settings.environment}

    @app.get("/api/info")
    async def info() -> dict:
        from paios.tools.registry import get_registry

        return {
            "version": __version__,
            "tools": get_registry().names(),
            "sandbox_roots": settings.security.sandbox_roots,
            "model": {
                "base_model": settings.model.base_model,
                "ollama_url": settings.model.ollama_url,
            },
        }

    # Serve the built frontend in production mode if it exists.
    dist = Path(settings.server.frontend_dist)
    if settings.environment == "prod" and dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    else:
        @app.get("/")
        async def root() -> dict:
            return {
                "name": "PAIOS",
                "version": __version__,
                "message": "PAIOS API is running.",
                "endpoints": {
                    "dashboard": "/api/dashboard",
                    "agents": "/api/agent",
                    "system": "/api/system",
                    "tools": "/api/tools",
                    "projects": "/api/projects",
                },
                "docs": "/docs",
                "websocket": "/ws",
            }

    return app


app = create_app()


def run() -> None:
    """Console-script entrypoint."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "paios.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.environment == "dev",
    )


if __name__ == "__main__":
    run()
