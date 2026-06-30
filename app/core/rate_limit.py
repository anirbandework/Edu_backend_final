"""Lightweight Redis-backed fixed-window rate limiting for sensitive endpoints.

Keyed by client IP + a scope string (and optionally by phone/account for the OTP
flows). FAILS OPEN if Redis is unavailable — availability over strictness, since a
cache outage shouldn't lock every user out — but logs so it's visible. Use it two ways:

    # as a route dependency (per-IP):
    @router.post("/login", dependencies=[Depends(rate_limiter("login", 10, 60))])

    # inline (per-phone/account), inside a handler/service:
    await enforce_rate_limit(phone, "otp_phone", 10, 3600)
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from .cache import cache_service

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honours the first X-Forwarded-For hop (set this only
    from a trusted proxy) and falls back to the socket peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(identifier: str, scope: str, limit: int, window_seconds: int) -> None:
    """Raise 429 if `identifier` exceeded `limit` requests for `scope` in the window."""
    key = f"rl:{scope}:{identifier}"
    count = await cache_service.incr(key, window_seconds)
    if count is None:
        return  # fail-open: cache unavailable
    if count > limit:
        logger.warning("Rate limit hit: scope=%s id=%s count=%s/%s", scope, identifier, count, limit)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait a moment and try again.",
            headers={"Retry-After": str(window_seconds)},
        )


def rate_limiter(scope: str, limit: int, window_seconds: int):
    """Return a FastAPI dependency that rate-limits the route per client IP."""
    async def _dep(request: Request) -> None:
        await enforce_rate_limit(client_ip(request), scope, limit, window_seconds)
    return _dep
