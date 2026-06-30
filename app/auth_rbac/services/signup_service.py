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

from ..security.password import hash_password_async
from ..security.principal import ROLE_AUTHORITY, ROLE_STAFF
from . import phone_service
from ...authority_management.models.authority import Authority
from ...staff_management.models.member import Member

# Only the authority (admin) is invite-created here (by the super-admin).
# Every other user is a dynamic `staff` user, created via /api/staff with an
# assigned rbac_role — not through this invite/signup path.
_MODEL_BY_ROLE = {
    ROLE_AUTHORITY: Authority,
    ROLE_STAFF: Member,  # member self-onboarding (Students page invite)
}
_HRID_FIELD = {
    ROLE_AUTHORITY: "authority_id",
    ROLE_STAFF: "staff_id",
}
_HRID_PREFIX = {ROLE_AUTHORITY: "AUTH", ROLE_STAFF: "STF"}


def _gen_hrid(role: str) -> str:
    return f"{_HRID_PREFIX[role]}-{secrets.token_hex(4).upper()}"


async def create_invited_user(
    db: AsyncSession, *, role: str, organisation_id: Optional[str] = None,
    first_name: str, last_name: str,
    email: Optional[str] = None, phone: Optional[str] = None,
    extra: Optional[dict] = None,
):
    """Create a user record in 'invited' state. Returns the created object."""
    # Reject a phone already in use before creating the record.
    if phone:
        await phone_service.assert_phone_available(db, phone)
    model = _MODEL_BY_ROLE[role]
    fields = dict(
        organisation_id=organisation_id,
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
        fields.setdefault("position", "Administrator")
        # Email is optional now (login is phone+password); only phone is required.
        if phone is None:
            fields["phone"] = ""  # NOT NULL on authority; real phone set at signup
    if role == ROLE_STAFF and phone is None:
        fields["phone"] = ""  # NOT NULL on members; real phone set at signup
    if extra:
        fields.update(extra)
    obj = model(**fields)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def find_pending_account_by_phone(db: AsyncSession, phone: str):
    """Find a created-but-not-yet-activated user (password_hash is NULL) by phone, across
    the identity tables. Powers first-login WITHOUT any invite/token: the admin creates the
    user, then the user sets their OWN password by phone. Returns (user, role) or (None, None)."""
    phone = (phone or "").strip()
    if not phone:
        return None, None
    for model, role in ((Authority, ROLE_AUTHORITY), (Member, ROLE_STAFF)):
        stmt = select(model).where(
            model.phone == phone,
            model.password_hash.is_(None),
            # A DEACTIVATED account (even one that never set a password) must NOT be
            # able to re-activate itself via first-login — only genuinely-pending users.
            model.status != "inactive",
        )
        if hasattr(model, "is_deleted"):
            stmt = stmt.where(model.is_deleted == False)  # noqa: E712
        user = (await db.execute(stmt)).scalars().first()
        if user:
            return user, role
    return None, None


async def complete_signup(
    db: AsyncSession, *, phone: str, password: str,
    first_name: Optional[str] = None, last_name: Optional[str] = None,
):
    """First login: find the created (password-less) user by phone, set their chosen
    password, and activate them. Purely phone-based — no invite token."""
    user, role = await find_pending_account_by_phone(db, phone)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account awaiting setup for this phone. Ask your admin to add you "
                   "first, or use 'Forgot password' if you've already set one.")

    user.phone = phone.strip()
    user.password_hash = await hash_password_async(password)
    user.status = "active"
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name

    # Give them the organisation's default role for their type if they don't carry one yet.
    if getattr(user, "rbac_role_id", None) is None:
        from ..access.service import RBACService
        default_role_id = await RBACService.get_default_role_id(db, user.organisation_id, role)
        if default_role_id:
            user.rbac_role_id = default_role_id

    # Never activate a role-less STAFF account (an active user must have a role). Raise
    # BEFORE commit so nothing persists — the user stays pending until an admin assigns a
    # role. (Defensive: members are normally created with a role.)
    if role == ROLE_STAFF and getattr(user, "rbac_role_id", None) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your account isn't assigned to a role yet. Ask your administrator to "
                   "assign one, then try signing in again.")

    await db.commit()
    await db.refresh(user)
    return user
