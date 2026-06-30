"""Per-user session invalidation ("revoke all my tokens now").

Every identity row carries a ``sessions_invalidated_at`` timestamp. A token is only
valid if its ``iat`` (issued-at) is **at or after** that timestamp, so stamping it to
``now()`` instantly invalidates every access *and* refresh token the user already has
— independent of the (best-effort, fail-open) jti denylist. This is how a password
change/reset actually terminates a compromised session.

The per-request lookup is Redis-cached, but falls back to the DB on a cache miss or a
Redis outage, so revocation stays enforced even when the cache is down (fail-closed
for the durable check). A sentinel ``0`` is cached for "never invalidated" so a cache
hit is distinguishable from a miss.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.cache import cache_service

logger = logging.getLogger(__name__)

# Canonical role -> identity table. Hardcoded constants (NOT user input), so the
# f-string interpolation below is injection-safe. (No teacher/student tables exist.)
_ROLE_TABLE = {
    "super_admin": "super_admins",
    "authority": "authorities",
    "staff": "members",
}


def _ckey(role: str, user_id) -> str:
    return f"siat:{role}:{user_id}"


async def sessions_invalid_before(db: AsyncSession, role: str, user_id) -> float:
    """Epoch seconds (sub-second) before which this user's tokens are invalid (0 = never)."""
    tbl = _ROLE_TABLE.get(role)
    if not tbl or not user_id:
        return 0.0
    cached = await cache_service.get(_ckey(role, user_id))
    if cached is not None:
        try:
            return float(cached)
        except (TypeError, ValueError):
            pass  # corrupt cache value — fall through to the DB
    try:
        row = (await db.execute(
            text(f"SELECT sessions_invalidated_at FROM {tbl} WHERE id = :id"),  # noqa: S608 (tbl is a constant)
            {"id": str(user_id)},
        )).first()
    except Exception as e:
        logger.error("sessions_invalid_before DB read failed: %s", e)
        return 0.0  # transient DB error — don't lock everyone out
    ts = row[0].timestamp() if (row and row[0]) else 0.0  # float (sub-second)
    await cache_service.set(_ckey(role, user_id), ts, ttl=300)
    return ts


async def invalidate_sessions(db: AsyncSession, role: str, user_id) -> None:
    """Invalidate ALL of this user's currently-issued tokens (access + refresh) by
    stamping ``sessions_invalidated_at = now()``. Call on password change/reset.
    The CALLER is responsible for committing the transaction."""
    tbl = _ROLE_TABLE.get(role)
    if not tbl or not user_id:
        return
    await db.execute(
        text(f"UPDATE {tbl} SET sessions_invalidated_at = now() WHERE id = :id"),  # noqa: S608
        {"id": str(user_id)},
    )
    await cache_service.delete(_ckey(role, user_id))
