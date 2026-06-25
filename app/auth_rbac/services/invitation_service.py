"""Invitation lifecycle: create signup links, validate them, mark accepted.

Role rules:
  super_admin       -> may invite: school_authority   (tenant_id required = the school)
  school_authority  -> may invite: teacher, student   (tenant = inviter's tenant)
"""
from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ..models.invitation import Invitation
from ..security.principal import (
    Principal, ROLE_SUPER_ADMIN, ROLE_AUTHORITY, ROLE_TEACHER, ROLE_STUDENT,
)

# who can invite whom
_ALLOWED_INVITES = {
    ROLE_SUPER_ADMIN: {ROLE_AUTHORITY},
    ROLE_AUTHORITY: {ROLE_TEACHER, ROLE_STUDENT},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def signup_url(token: str) -> str:
    return f"{settings.app_base_url}/signup?token={token}"


async def create_invitation(
    db: AsyncSession,
    inviter: Principal,
    *,
    role: str,
    tenant_id: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    target_user_id: Optional[str] = None,
) -> Invitation:
    # 1) authorize the inviter -> role
    allowed = _ALLOWED_INVITES.get(inviter.role, set())
    if role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Your role cannot invite a '{role}'.")

    # 2) resolve the tenant the invitee joins
    if inviter.is_super_admin:
        # super-admin may invite an ADMIN with no school yet (tenant_id None);
        # the admin creates their school(s) after signing up.
        effective_tenant = tenant_id
    else:
        # non-super-admins can only invite into their own tenant
        effective_tenant = inviter.tenant_id
        if not effective_tenant:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Inviter has no tenant.")

    # 3) if a phone was supplied AND no user was pre-created, reject duplicates.
    #    (When target_user_id is set, the user was already created+checked.)
    if phone and not target_user_id:
        await assert_phone_available(db, phone)

    invitation = Invitation(
        tenant_id=effective_tenant,
        role=role,
        token=secrets.token_urlsafe(32),
        status="pending",
        expires_at=_now() + timedelta(hours=settings.invite_ttl_hours),
        phone=(phone.strip() if phone else None),
        email=email,
        first_name=first_name,
        last_name=last_name,
        target_user_id=target_user_id,
        created_by=inviter.user_id,
        created_by_role=inviter.role,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    return invitation


async def get_valid_invitation(db: AsyncSession, token: str) -> Invitation:
    inv = (await db.execute(select(Invitation).where(Invitation.token == token))).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invitation link.")
    if inv.status == "accepted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This invitation has already been used.")
    if inv.status == "revoked":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invitation was revoked.")
    expires = inv.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if _now() > expires:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invitation has expired.")
    return inv


async def mark_accepted(db: AsyncSession, inv: Invitation, user_id: str) -> None:
    inv.status = "accepted"
    inv.accepted_at = _now()
    inv.target_user_id = user_id
    await db.commit()


async def assert_phone_available(db: AsyncSession, phone: str, *, exclude_user_id: Optional[str] = None) -> None:
    """Raise 409 if any active user (student/teacher/authority) already uses this phone."""
    from ...student_management.models.student import Student
    from ...teacher_management.models.teacher import Teacher
    from ...school_authority_management.models.school_authority import SchoolAuthority

    phone = phone.strip()
    for model in (SchoolAuthority, Teacher, Student):
        stmt = select(model.id).where(model.phone == phone)
        if hasattr(model, "is_deleted"):
            stmt = stmt.where(model.is_deleted == False)  # noqa: E712
        rows = (await db.execute(stmt)).scalars().all()
        for rid in rows:
            if exclude_user_id and str(rid) == str(exclude_user_id):
                continue
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="This phone number is already registered.")
