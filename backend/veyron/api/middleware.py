"""Rate limiting middleware.

Simple in-memory rate limiter using a sliding window approach.
In production, replace with a distributed approach (Redis, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from veyron.api.auth import verify_token
from veyron.config import get_settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit requests per client IP.

    Configured with max requests per window. Returns 429 when exceeded.
    """

    def __init__(
        self,
        app: Any,
        max_requests: int = 60,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path.rstrip("/")
        # Skip rate limiting for WebSocket upgrades, docs, and non-standard methods.
        if path == "/ws" or request.method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - self.window_seconds

        async with self._lock:
            timestamps = self._clients[client_ip]
            self._clients[client_ip] = [t for t in timestamps if t > window_start]
            if len(self._clients[client_ip]) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Try again later."},
                    headers={"Retry-After": str(self.window_seconds)},
                )
            self._clients[client_ip].append(now)

        return await call_next(request)


# ── Request logging middleware (diagnostics) ────────────────────────────


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Log every request with method, URL, response status, and latency.

    Logs a single ``METHOD PATH STATUS LATENCYms`` line per request.  When a
    request exceeds 30 seconds a warning-level message is emitted.  Unhandled
    exceptions are caught and returned as 500 so the event loop is never left
    hanging.
    """

    _TIMEOUT_WARN_SECONDS = 30

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.exception(
                "REQ %s %s | UNHANDLED EXCEPTION after %.0fms: %s",
                request.method, request.url.path, latency_ms, exc,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )

        latency_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s %s %.0fms",
            request.method, request.url.path, response.status_code, latency_ms,
        )

        if latency_ms > self._TIMEOUT_WARN_SECONDS * 1000:
            logger.warning(
                "SLOW %s %s %s %.0fms (exceeded %ss threshold)",
                request.method, request.url.path, response.status_code,
                latency_ms, self._TIMEOUT_WARN_SECONDS,
            )

        origin = request.headers.get("Origin", "(none)")
        acao = response.headers.get("access-control-allow-origin", "(not set)")
        ua = request.headers.get("User-Agent", "")[:80]
        logger.debug(
            "EXTRA %s %s | Origin: %s | UA: %s | ACAO: %s",
            request.method, request.url.path, origin, ua, acao,
        )
        return response


# ── Request ID middleware ───────────────────────────────────────────────


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add a unique request ID to every response."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        from uuid import uuid4

        request_id = uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ── Auth middleware ─────────────────────────────────────────────────────


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token authentication middleware.

    Reads ``api_auth_token`` from ``ServerConfig``. When set, every request
    **except** those with paths listed in ``exempt_paths`` must carry an
    ``Authorization: Bearer <token>`` header matching the configured value.

    When ``api_auth_token`` is ``None`` (the default) all requests pass
    through without authentication, preserving the existing dev behaviour.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.exempt_path_prefixes: tuple[str, ...] = (
            "/api/health", "/api/info", "/ws", "/docs", "/openapi.json", "/redoc",
        )

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        settings = get_settings()
        token = settings.server.api_auth_token
        if token is None:
            return await call_next(request)

        path = request.url.path.rstrip("/")
        if any(path == ep or path.startswith(ep) for ep in self.exempt_path_prefixes):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        bearer_token = auth_header.removeprefix("Bearer ").strip()
        if not verify_token(bearer_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        return await call_next(request)
