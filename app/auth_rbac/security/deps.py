"""FastAPI dependencies that enforce authentication and authorization.

These are the ONLY sanctioned way to learn who the caller is. Handlers must never
trust a user_id / organisation_id / role taken from the path, query, or body for
authorization decisions — use the injected Principal instead.
"""
from __future__ import annotations
import logging
from typing import Iterable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .tokens import decode_token, TokenError, ACCESS
from .principal import Principal
from .sessions import sessions_invalid_before
from ...core.database import get_db

logger = logging.getLogger(__name__)

# auto_error=False so we can raise a uniform 401 with WWW-Authenticate ourselves.
_bearer = HTTPBearer(auto_error=False)


async def _is_revoked(jti: Optional[str]) -> bool:
    """Best-effort denylist check (Redis). Fail-open if cache is unavailable —
    the token still had to be validly signed and unexpired to get here."""
    if not jti:
        return False
    try:
        from ...core.cache import cache_service
        val = await cache_service.get(f"denylist:{jti}")
        return val is not None
    except Exception as e:  # pragma: no cover - cache optional
        logger.debug(f"denylist check skipped: {e}")
        return False


async def get_current_principal(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """Resolve and return the authenticated caller, or raise 401."""
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(creds.credentials, expected_type=ACCESS)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if await _is_revoked(payload.get("jti")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Session revocation: a password change/reset (or admin reset) stamps the user's
    # sessions_invalidated_at, instantly killing every token issued before then.
    iat = payload.get("iat")
    if iat is not None:
        invalid_before = await sessions_invalid_before(db, payload.get("role", ""), payload["sub"])
        if invalid_before and float(iat) < invalid_before:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired — please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Principal(
        user_id=payload["sub"],
        role=payload.get("role", ""),
        organisation_id=payload.get("organisation_id"),
        group_id=payload.get("group_id"),
        jti=payload.get("jti"),
    )


def require_roles(*allowed: str):
    """Dependency factory: require the caller's role to be one of `allowed`
    (super_admin always passes)."""
    allowed_set = set(allowed)

    async def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.is_super_admin or principal.role in allowed_set:
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for this operation",
        )

    return _dep


def require_super_admin(principal: Principal = Depends(get_current_principal)) -> Principal:
    if not principal.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin privilege required",
        )
    return principal


# Convenience dependencies
require_authority = require_roles("authority")
require_staff = require_roles("authority", "teacher")


def assert_same_organisation(principal: Principal, organisation_id) -> None:
    """Raise 403 unless the principal may act on `organisation_id`. Call this in handlers
    after resolving the target object's organisation, OR before using a client-supplied
    organisation_id. Super-admins bypass."""
    if not principal.can_access_organisation(organisation_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organisation access denied",
        )
