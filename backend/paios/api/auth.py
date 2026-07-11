"""Authentication dependencies.

Placeholder for future auth integration. Currently allows all requests.
Replace with real JWT/OAuth verification when auth is implemented.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from paios.api.schemas import AuthToken

_security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> AuthToken:
    """Extract or create an auth token for the current request.

    Currently accepts any bearer token or anonymous access. When real auth
    is added, validate the token here and return a proper AuthToken.
    """
    if credentials is None:
        return AuthToken(sub="anonymous", scopes=[])
    # Future: validate credentials.credentials (JWT, API key, etc.)
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
    # Future: validate credentials.credentials
    return AuthToken(sub=credentials.credentials[:16], scopes=[])
