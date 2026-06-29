"""Password hashing using bcrypt directly.

We use the `bcrypt` library directly rather than passlib because passlib 1.7.x
is incompatible with bcrypt >= 4 (it crashes reading bcrypt.__about__).
bcrypt has a hard 72-byte input limit, so we truncate defensively.
"""
import asyncio
import bcrypt

_BCRYPT_ROUNDS = 12
_MAX_BYTES = 72


def _to_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash (utf-8 string) for the given plaintext password."""
    if not password:
        raise ValueError("password must not be empty")
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verify a plaintext password against a stored bcrypt hash."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_to_bytes(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- async wrappers ---------------------------------------------------------
# bcrypt at 12 rounds is ~150-300ms of pure CPU. Calling it directly inside an
# async request handler blocks the whole event loop for that worker, serialising
# every concurrent request behind it. Offload to a thread so the loop stays free.
# (The sync versions above are kept for non-async callers such as the seed scripts.)
async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)
