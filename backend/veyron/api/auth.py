"""Authentication dependencies and helpers.

Provides the `verify_token` helper for middleware use, plus FastAPI dependency
injection helpers (`get_current_user`, `require_auth`) for route-level auth.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from veyron.api.schemas import AuthToken
from veyron.config import get_settings

_security = HTTPBearer(auto_error=False)


def verify_token(token: str) -> bool:
    """Check a bearer token against the configured api_auth_token.

    Uses constant-time comparison to avoid timing side-channels.
    Returns True if the token is valid or if auth is disabled (token is None).
    """
    settings = get_settings()
    expected = settings.server.api_auth_token
    if expected is None:
        return True
    return hmac.compare_digest(token, expected)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> AuthToken:
    """Extract or create an auth token for the current request.

    Currently accepts any bearer token or anonymous access. When real auth
    is added, validate the token here and return a proper AuthToken.
    """
    if credentials is None:
        return AuthToken(sub="anonymous", scopes=[])
    return AuthToken(sub=credentials.credentials[:16], scopes=[])


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> AuthToken:
    """Require authentication for a route.

    Raises 401 if no bearer token is provided.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return AuthToken(sub=credentials.credentials[:16], scopes=[])
