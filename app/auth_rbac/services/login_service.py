"""Credential verification for login.

Looks up a user by email across the three identity tables (school_authorities,
teachers, students), verifies the bcrypt password, and returns a minimal identity
tuple. Also supports a config-bootstrapped platform super-admin.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ..security.password import verify_password
from ..security.principal import (
    ROLE_SUPER_ADMIN, ROLE_AUTHORITY, ROLE_TEACHER, ROLE_STUDENT, ROLE_STAFF,
)
from ...school_authority_management.models.school_authority import SchoolAuthority
from ...teacher_management.models.teacher import Teacher
from ...student_management.models.student import Student
from ...staff_management.models.staff_user import StaffUser


@dataclass
class Identity:
    user_id: str
    role: str
    tenant_id: Optional[str]


# (model, role) in priority order
_IDENTITY_TABLES = [
    (SchoolAuthority, ROLE_AUTHORITY),
    (StaffUser, ROLE_STAFF),
    (Teacher, ROLE_TEACHER),
    (Student, ROLE_STUDENT),
]


async def authenticate(
    db: AsyncSession, *, identifier: str, password: str
) -> Optional[Identity]:
    """Return an Identity if credentials are valid, else None.

    `identifier` is the user's PHONE number (the login id). The platform
    super-admin logs in with its configured email in the same field.
    Order: super-admin (config), then authority -> teacher -> student by phone.
    Only 'active' accounts with a password set can log in."""
    if not identifier or not password:
        return None

    ident = identifier.strip()

    # 1) Platform super-admin (seeded in super_admins; login by phone OR email)
    from ..models.super_admin import SuperAdmin
    sa_stmt = select(SuperAdmin).where(
        (SuperAdmin.phone == ident) | (SuperAdmin.email == ident.lower())
    )
    if hasattr(SuperAdmin, "is_deleted"):
        sa_stmt = sa_stmt.where(SuperAdmin.is_deleted == False)  # noqa: E712
    sa = (await db.execute(sa_stmt)).scalars().first()
    if sa and sa.status == "active" and sa.password_hash and verify_password(password, sa.password_hash):
        return Identity(user_id=str(sa.id), role=ROLE_SUPER_ADMIN, tenant_id=None)

    # 2) Real users, by PHONE across the three tables
    for model, role in _IDENTITY_TABLES:
        stmt = select(model).where(model.phone == ident)
        if hasattr(model, "is_deleted"):
            stmt = stmt.where(model.is_deleted == False)  # noqa: E712
        rows = (await db.execute(stmt)).scalars().all()
        for user in rows:
            if getattr(user, "status", "active") != "active":
                continue
            if not getattr(user, "password_hash", None):
                continue
            if verify_password(password, user.password_hash):
                return Identity(
                    user_id=str(user.id),
                    # Canonical role from the identity table, NOT the free-text
                    # `role` column (which may be 'principal', 'admin', etc.).
                    role=role,
                    tenant_id=str(user.tenant_id) if getattr(user, "tenant_id", None) else None,
                )
    return None


async def find_active_user_by_phone(db: AsyncSession, phone: str):
    """Return (model_obj, role) for an active user with this phone, or (None, None).
    Used by forgot-password."""
    phone = phone.strip()
    for model, role in _IDENTITY_TABLES:
        stmt = select(model).where(model.phone == phone)
        if hasattr(model, "is_deleted"):
            stmt = stmt.where(model.is_deleted == False)  # noqa: E712
        user = (await db.execute(stmt)).scalars().first()
        if user and getattr(user, "status", "active") == "active":
            return user, role  # canonical table role
    return None, None
