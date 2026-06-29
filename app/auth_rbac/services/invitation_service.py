"""Phone-uniqueness guard for onboarding.

The old invitation / signup-link system (one-time tokens, invite roles) was REMOVED:
onboarding is now password-less first-login (phone + OTP, no links). The only piece
that survived is the phone-availability check below, used when the super-admin creates
an admin or resets an admin's password. (Kept in this module to avoid churning the
`invitation_service.assert_phone_available` import sites.)
"""
from __future__ import annotations
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def assert_phone_available(db: AsyncSession, phone: str, *, exclude_user_id: Optional[str] = None) -> None:
    """Raise 409 if any NON-DELETED user (admin or member) already uses this phone —
    phone is the login id. Soft-deleted users free their phone."""
    from ...staff_management.models.member import Member
    from ...authority_management.models.authority import Authority

    phone = phone.strip()
    for model in (Authority, Member):
        stmt = select(model.id).where(model.phone == phone)
        if hasattr(model, "is_deleted"):
            stmt = stmt.where(model.is_deleted == False)  # noqa: E712
        rows = (await db.execute(stmt)).scalars().all()
        for rid in rows:
            if exclude_user_id and str(rid) == str(exclude_user_id):
                continue
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="This phone number is already registered.")
