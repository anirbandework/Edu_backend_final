"""JWT access/refresh token creation and verification (PyJWT, HS256)."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from ...core.config import settings

ACCESS = "access"
REFRESH = "refresh"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or of the wrong type."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(*, user_id: str, role: str, tenant_id: Optional[str]) -> str:
    now = _now()
    payload = {
        "sub": str(user_id),
        "role": role,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "type": ACCESS,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    return _encode(payload)


def create_refresh_token(*, user_id: str, role: str, tenant_id: Optional[str]) -> str:
    now = _now()
    payload = {
        "sub": str(user_id),
        "role": role,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "type": REFRESH,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.refresh_token_expire_days)).timestamp()),
    }
    return _encode(payload)


def decode_token(token: str, *, expected_type: Optional[str] = None) -> dict:
    """Decode & verify a JWT. Raises TokenError on any problem."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("token expired") from e
    except jwt.PyJWTError as e:
        raise TokenError("invalid token") from e
    if expected_type and payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token")
    if not payload.get("sub"):
        raise TokenError("token missing subject")
    return payload
