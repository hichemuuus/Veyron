"""Rate limiting middleware.

Simple in-memory rate limiter using a sliding window approach.
In production, replace with a distributed approach (Redis, etc.).
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


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
        # Skip rate limiting for static files and WebSocket upgrades.
        if request.url.path.startswith("/ws") or request.method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
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


# ── Request ID middleware ───────────────────────────────────────────────


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add a unique request ID to every response."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        from uuid import uuid4

        request_id = uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
