"""FastAPI dependencies that enforce authentication and authorization.

These are the ONLY sanctioned way to learn who the caller is. Handlers must never
trust a user_id / tenant_id / role taken from the path, query, or body for
authorization decisions — use the injected Principal instead.
"""
from __future__ import annotations
import logging
from typing import Iterable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .tokens import decode_token, TokenError, ACCESS
from .principal import Principal

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
    return Principal(
        user_id=payload["sub"],
        role=payload.get("role", ""),
        tenant_id=payload.get("tenant_id"),
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
require_authority = require_roles("school_authority")
require_staff = require_roles("school_authority", "teacher")


def assert_same_tenant(principal: Principal, tenant_id) -> None:
    """Raise 403 unless the principal may act on `tenant_id`. Call this in handlers
    after resolving the target object's tenant, OR before using a client-supplied
    tenant_id. Super-admins bypass."""
    if not principal.can_access_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-tenant access denied",
        )
