"""Account creation (invite) + activation (signup).

Invite endpoints PRE-CREATE the user record (status='invited', no password) so
all NOT-NULL columns are satisfied by the creator; signup then ACTIVATES it by
setting the verified phone + password and flipping status to 'active'.
"""
from __future__ import annotations
import secrets
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.invitation import Invitation
from ..security.password import hash_password
from ..security.principal import ROLE_AUTHORITY, ROLE_TEACHER, ROLE_STUDENT
from . import invitation_service
from ...student_management.models.student import Student
from ...teacher_management.models.teacher import Teacher
from ...school_authority_management.models.school_authority import SchoolAuthority

_MODEL_BY_ROLE = {
    ROLE_AUTHORITY: SchoolAuthority,
    ROLE_TEACHER: Teacher,
    ROLE_STUDENT: Student,
}
_HRID_FIELD = {
    ROLE_AUTHORITY: "authority_id",
    ROLE_TEACHER: "teacher_id",
    ROLE_STUDENT: "student_id",
}
_HRID_PREFIX = {ROLE_AUTHORITY: "AUTH", ROLE_TEACHER: "TCH", ROLE_STUDENT: "STU"}


def _gen_hrid(role: str) -> str:
    return f"{_HRID_PREFIX[role]}-{secrets.token_hex(4).upper()}"


async def create_invited_user(
    db: AsyncSession, *, role: str, tenant_id: Optional[str] = None,
    first_name: str, last_name: str,
    email: Optional[str] = None, phone: Optional[str] = None,
    extra: Optional[dict] = None,
):
    """Create a user record in 'invited' state. Returns the created object."""
    # Reject a phone already in use before creating the record.
    if phone:
        await invitation_service.assert_phone_available(db, phone)
    model = _MODEL_BY_ROLE[role]
    fields = dict(
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        status="invited",
        role=role,
    )
    fields[_HRID_FIELD[role]] = _gen_hrid(role)
    if email is not None:
        fields["email"] = email
    if phone is not None:
        fields["phone"] = phone
    # NOT-NULL columns that vary by model
    if role == ROLE_AUTHORITY:
        fields.setdefault("position", "School Authority")
        # Email is optional now (login is phone+password); only phone is required.
        if phone is None:
            fields["phone"] = ""  # NOT NULL on authority; real phone set at signup
    if extra:
        fields.update(extra)
    obj = model(**fields)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def complete_signup(
    db: AsyncSession, inv: Invitation, *, phone: str, password: str,
    first_name: Optional[str] = None, last_name: Optional[str] = None,
):
    """Activate the invited user: set verified phone + password, status=active."""
    model = _MODEL_BY_ROLE.get(inv.role)
    if not model or not inv.target_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed invitation.")

    user = (await db.execute(select(model).where(model.id == inv.target_user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invited account no longer exists.")
    if getattr(user, "status", None) == "active" and getattr(user, "password_hash", None):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This account is already active.")

    # phone must be unique among active users (allow the invite's own pre-set phone)
    await invitation_service.assert_phone_available(db, phone, exclude_user_id=str(user.id))

    user.phone = phone.strip()
    user.password_hash = hash_password(password)
    user.status = "active"
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name

    # Assign the tenant's default RBAC role for this user_type (inv.role is already the
    # rbac user_type: 'teacher' | 'student' | 'school_authority'). No-op if the tenant
    # has no default configured, or the user already carries a role.
    if getattr(user, "rbac_role_id", None) is None:
        from ..access.service import RBACService
        default_role_id = await RBACService.get_default_role_id(db, user.tenant_id, inv.role)
        if default_role_id:
            user.rbac_role_id = default_role_id

    await db.commit()
    await db.refresh(user)

    await invitation_service.mark_accepted(db, inv, str(user.id))
    return user
