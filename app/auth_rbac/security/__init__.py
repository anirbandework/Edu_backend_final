"""Authentication & authorization primitives: password hashing, JWT tokens,
the request Principal, and FastAPI dependencies that enforce them."""
from .password import hash_password, verify_password
from .tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    TokenError,
)
from .principal import Principal, ROLE_SUPER_ADMIN, ROLE_AUTHORITY, ROLE_TEACHER, ROLE_STUDENT
from .deps import (
    get_current_principal,
    require_roles,
    require_super_admin,
    require_authority,
    require_staff,
    assert_same_tenant,
)

__all__ = [
    "hash_password", "verify_password",
    "create_access_token", "create_refresh_token", "decode_token", "TokenError",
    "Principal", "ROLE_SUPER_ADMIN", "ROLE_AUTHORITY", "ROLE_TEACHER", "ROLE_STUDENT",
    "get_current_principal", "require_roles", "require_super_admin",
    "require_authority", "require_staff", "assert_same_tenant",
]
