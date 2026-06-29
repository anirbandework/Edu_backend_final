"""Credential verification for login.

Looks up a user by email across the three identity tables (authorities,
teachers, students), verifies the bcrypt password, and returns a minimal identity
tuple. Also supports a config-bootstrapped platform super-admin.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ..security.password import verify_password_async
from ..security.principal import (
    ROLE_SUPER_ADMIN, ROLE_AUTHORITY, ROLE_STAFF,
)
from ...authority_management.models.authority import Authority
from ...staff_management.models.member import Member


class AccountInactiveError(Exception):
    """Raised when the credentials are VALID but the account, its organisation, or
    its institution group has been deactivated. Carries a user-facing message, so the
    login/refresh routes can return a clear 403 (e.g. "This organisation has been
    deactivated."). Raised only AFTER the password verifies, so we never reveal which
    phones/orgs exist to an unauthenticated caller."""


@dataclass
class Identity:
    user_id: str
    role: str
    organisation_id: Optional[str]
    # The institution group: set for an admin (authority.group_id). For staff it
    # stays None in the token and is resolved from their organisation when needed.
    group_id: Optional[str] = None


# (model, role) in priority order. The system has THREE user types: the platform
# super-admin (above), the authority (admin), and the unified dynamic
# `staff` user — every non-admin (Teacher/Professor/Student/Parent/...) is a staff
# user whose role+pages come from their assigned rbac_role. Legacy teacher/student
# identity tables are no longer login identities.
_IDENTITY_TABLES = [
    (Authority, ROLE_AUTHORITY),
    (Member, ROLE_STAFF),
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
    if sa and sa.status == "active" and sa.password_hash and await verify_password_async(password, sa.password_hash):
        return Identity(user_id=str(sa.id), role=ROLE_SUPER_ADMIN, organisation_id=None)

    # 2) Real users, by PHONE across the identity tables
    for model, role in _IDENTITY_TABLES:
        stmt = select(model).where(model.phone == ident)
        if hasattr(model, "is_deleted"):
            stmt = stmt.where(model.is_deleted == False)  # noqa: E712
        rows = (await db.execute(stmt)).scalars().all()
        for user in rows:
            if not getattr(user, "password_hash", None):
                continue
            if not await verify_password_async(password, user.password_hash):
                continue
            # Password is correct. Gate on status:
            status_val = getattr(user, "status", "active")
            if status_val == "inactive":
                # Explicitly deactivated by a super-admin.
                raise AccountInactiveError(
                    "Your account has been deactivated. Please contact your administrator.")
            if status_val != "active":
                # e.g. 'invited' — a password exists but first-login isn't complete;
                # don't log in (preserves the prior behaviour for non-active accounts).
                continue
            org_id = str(user.organisation_id) if getattr(user, "organisation_id", None) else None
            grp_id = str(user.group_id) if getattr(user, "group_id", None) else None
            # Organisation / institution-group deactivation gate (clear message).
            await assert_active(db, role=role, organisation_id=org_id, group_id=grp_id)
            return Identity(
                user_id=str(user.id),
                # Canonical role from the identity table, NOT the free-text
                # `role` column (which may be 'principal', 'admin', etc.).
                role=role,
                organisation_id=org_id,
                group_id=grp_id,
            )
    return None


async def _group_active(db: AsyncSession, group_id: str) -> bool:
    """True unless the institution group exists and is explicitly inactive / soft-deleted."""
    r = (await db.execute(text(
        "SELECT is_active, is_deleted FROM institution_groups WHERE id = :id"
    ), {"id": str(group_id)})).first()
    if r is None:
        return True  # unknown group → don't block
    return bool(r[0]) and not bool(r[1])


async def _org_status(db: AsyncSession, organisation_id: str):
    """Return (active: bool, group_id: Optional[str]) for an organisation."""
    r = (await db.execute(text(
        "SELECT is_active, group_id, is_deleted FROM organisations WHERE id = :id"
    ), {"id": str(organisation_id)})).first()
    if r is None:
        return True, None  # unknown org → don't block
    return (bool(r[0]) and not bool(r[2])), (str(r[1]) if r[1] else None)


async def assert_active(
    db: AsyncSession, *, role: str, organisation_id: Optional[str],
    group_id: Optional[str],
) -> None:
    """Raise AccountInactiveError if the caller's organisation or institution group is
    deactivated. Shared by login and refresh (the account-status gate lives in the
    login loop, since refresh has no live user row)."""
    # Institution-group gate. For an ADMIN the group is on the token; staff inherit it
    # from their organisation (resolved below), so this catches the whole group.
    if group_id and not await _group_active(db, group_id):
        raise AccountInactiveError(
            "Your institution group has been deactivated. Please contact the platform administrator.")
    # Organisation gate — only staff are bound to a single organisation. Admins are
    # group-level and may still sign in to manage/reactivate a dead org.
    if role == ROLE_STAFF and organisation_id:
        active, org_group_id = await _org_status(db, organisation_id)
        if not active:
            raise AccountInactiveError(
                "This organisation has been deactivated. Please contact your administrator.")
        if org_group_id and not await _group_active(db, org_group_id):
            raise AccountInactiveError(
                "Your institution group has been deactivated. Please contact your administrator.")


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
