"""Phone OTP service (Redis-backed via cache_service).

Dev mode: every OTP is settings.otp_dev_code ('999999') and is logged, not SMS'd.
Handles the edge cases: resend cooldown, expiry, and a max wrong-attempt lockout.
Swap _generate_code + _deliver for a real SMS provider to go live.
"""
from __future__ import annotations
import logging
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, status

from ...core.config import settings
from ...core.cache import cache_service

logger = logging.getLogger(__name__)

# purposes
PURPOSE_SIGNUP = "signup"
PURPOSE_RESET = "reset"


def _otp_key(purpose: str, phone: str) -> str:
    return f"otp:{purpose}:{phone}"


def _cooldown_key(purpose: str, phone: str) -> str:
    return f"otp_cd:{purpose}:{phone}"


def _generate_code() -> str:
    if settings.otp_dev_mode:
        return settings.otp_dev_code
    return "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))


def _deliver(phone: str, code: str) -> None:
    if settings.otp_dev_mode:
        logger.info(f"[DEV OTP] phone={phone} code={code}")
    else:
        # TODO: integrate SMS provider (Twilio / AWS SNS / MSG91) here.
        logger.warning("OTP SMS delivery not configured; set up a provider.")


@dataclass
class OtpRequestResult:
    sent: bool
    # In dev mode we surface the code so the flow is testable without SMS.
    dev_code: str | None = None


async def request_otp(phone: str, purpose: str) -> OtpRequestResult:
    """Issue an OTP for (phone, purpose). Enforces a resend cooldown."""
    phone = phone.strip()
    if await cache_service.get(_cooldown_key(purpose, phone)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait before requesting another code.",
        )
    code = _generate_code()
    payload = {"code": code, "attempts": 0, "exp": int(time.time()) + settings.otp_ttl_seconds}
    await cache_service.set(_otp_key(purpose, phone), payload, ttl=settings.otp_ttl_seconds)
    await cache_service.set(_cooldown_key(purpose, phone), "1", ttl=settings.otp_resend_cooldown_seconds)
    _deliver(phone, code)
    return OtpRequestResult(sent=True, dev_code=code if settings.otp_dev_mode else None)


async def verify_otp(phone: str, purpose: str, code: str) -> None:
    """Verify an OTP. Raises 400/429 on any problem; consumes it on success."""
    phone = phone.strip()
    key = _otp_key(purpose, phone)
    blob = await cache_service.get(key)
    if not blob:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Code expired or not requested. Request a new one.")
    now = int(time.time())
    if now > int(blob.get("exp", 0)):
        await cache_service.delete(key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code expired. Request a new one.")
    if int(blob.get("attempts", 0)) >= settings.otp_max_attempts:
        await cache_service.delete(key)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many incorrect attempts. Request a new code.")
    if str(code).strip() != str(blob.get("code")):
        blob["attempts"] = int(blob.get("attempts", 0)) + 1
        remaining_ttl = max(1, int(blob["exp"]) - now)
        await cache_service.set(key, blob, ttl=remaining_ttl)
        left = settings.otp_max_attempts - blob["attempts"]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Incorrect code. {max(0, left)} attempt(s) left.")
    # success — consume it so it can't be reused
    await cache_service.delete(key)
