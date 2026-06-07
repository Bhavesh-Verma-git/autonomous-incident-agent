"""
api/auth.py — API key authentication dependency.

How it works:
    Every protected route depends on verify_api_key().
    FastAPI reads the 'X-Api-Key' header from the incoming request
    and passes it to this function. If the key is wrong (or missing),
    the request is rejected immediately with a 403 Forbidden error.
    If the key is correct, the route handler runs normally.

Why hmac.compare_digest?
    A normal == comparison can leak information through timing —
    a slightly different response time for "first character wrong"
    vs "all characters wrong" can theoretically help an attacker
    guess the key one character at a time.
    hmac.compare_digest always takes the same amount of time,
    making that attack impossible.

Usage in routes:
    from api.auth import ApiKeyDep

    @router.get("/example")
    async def example(auth: ApiKeyDep):
        ...

Usage on a whole router (in app.py):
    app.include_router(incidents_router, dependencies=[Depends(verify_api_key)])
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Depends, Header, HTTPException, status
from typing import Annotated

import config

log = logging.getLogger(__name__)


def verify_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """
    FastAPI dependency — acts as a security guard for every protected route.

    Called automatically by FastAPI before the route handler runs.
    Rejects the request if the key is missing or wrong.

    Args:
        x_api_key: The value of the 'X-Api-Key' header sent by the caller.
                   FastAPI reads this automatically from the request headers.

    Raises:
        HTTPException 401: If no API key was sent at all.
        HTTPException 403: If the key was sent but it's wrong.
    """
    # If no API_KEY is configured in .env, auth is disabled (dev mode).
    # Log a warning so developers know auth is off.
    if not config.API_KEY:
        log.warning(
            "[auth] API_KEY is not set in .env — authentication is DISABLED. "
            "Set API_KEY in your .env file before deploying."
        )
        return  # Skip auth check — useful for local development

    # No key was sent at all
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Add 'X-Api-Key: <your-key>' to your request headers.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Key was sent but it's wrong — use hmac.compare_digest to prevent timing attacks
    if not hmac.compare_digest(x_api_key, config.API_KEY):
        log.warning("[auth] Rejected request with invalid API key.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    # Key is correct — allow the request through (no return value needed)


# Type alias so routes can write `auth: ApiKeyDep` instead of the long Depends() form
ApiKeyDep = Annotated[None, Depends(verify_api_key)]
