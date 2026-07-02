"""User profile lookup for GET /api/auth/user-profile/{user_id}.

Identity-only: returns the user's own record across the three identity tables.
Module/tab permissions are served separately by /api/access/my-permissions, so this
no longer depends on the retired page-based RBAC tables (Role/UserRole/PagePermission/
OrganisationPageAccess).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import UUID

from ...authority_management.models.authority import Authority
from ...staff_management.models.member import Member


def _iso(dt):
    return dt.isoformat() if dt else None


class AuthService:

    @staticmethod
    async def get_identity_record(db: AsyncSession, role: str, user_id):
        """Return the ORM identity row (with password_hash) for a (role, id), or
        None. Used by self change-password."""
        from ..models.super_admin import SuperAdmin
        model = {
            "super_admin": SuperAdmin,
            "authority": Authority,
            "staff": Member,
        }.get(role)
        if not model:
            return None
        return (await db.execute(select(model).where(model.id == user_id))).scalar_one_or_none()

    @staticmethod
    async def get_user_profile(db: AsyncSession, user_id: UUID, organisation_id: UUID = None) -> Optional[dict]:
        """Return the identity profile for a user, searching the three identity tables
        (super-admin, authority, unified staff). There is no teacher/student table — every
        org-created person is a Member; what they ARE comes from their role's capabilities,
        not a profile.category string."""
        # Super-admin (platform owner; no organisation)
        from ..models.super_admin import SuperAdmin
        sa = (await db.execute(select(SuperAdmin).where(SuperAdmin.id == user_id))).scalar_one_or_none()
        if sa:
            return {
                "user_id": str(sa.id),
                "user_type": "SUPER_ADMIN",
                "role": "super_admin",
                "first_name": getattr(sa, "first_name", None) or "Super",
                "last_name": getattr(sa, "last_name", None) or "Admin",
                "email": sa.email,
                "phone": sa.phone,
                "status": getattr(sa, "status", "active"),
                "last_login": _iso(getattr(sa, "last_login", None)),
                "organisation_id": None,
            }

        # Unified dynamic-role staff
        q = select(Member).where(Member.id == user_id)
        if organisation_id:
            q = q.where(Member.organisation_id == organisation_id)
        staff = (await db.execute(q)).scalar_one_or_none()
        if staff:
            prof = staff.profile or {}
            return {
                "user_id": str(staff.id),
                "user_type": "STAFF",
                "role": "staff",
                "staff_id": staff.staff_id,
                "first_name": staff.first_name,
                "last_name": staff.last_name,
                "email": staff.email,
                "phone": staff.phone,
                "date_of_birth": _iso(staff.date_of_birth),
                "address": staff.address,
                "gender": staff.gender,
                "position": staff.position,
                "status": staff.status,
                # The member's dynamic role pointer; its name/pages/capabilities come from
                # /api/access/my-permissions, never reconstructed from a magic category.
                "rbac_role_id": str(staff.rbac_role_id) if staff.rbac_role_id else None,
                "profile": prof,
                "last_login": _iso(staff.last_login),
                "organisation_id": str(staff.organisation_id) if staff.organisation_id else None,
            }

        # Organisation authority
        q = select(Authority).where(Authority.id == user_id)
        if organisation_id:
            q = q.where(Authority.organisation_id == organisation_id)
        auth = (await db.execute(q)).scalar_one_or_none()
        if auth:
            return {
                "user_id": str(auth.id),
                "user_type": "AUTHORITY",
                "role": "admin",  # for frontend navigation
                "authority_id": auth.authority_id,
                "first_name": auth.first_name,
                "last_name": auth.last_name,
                "email": auth.email,
                "phone": auth.phone,
                "date_of_birth": _iso(auth.date_of_birth),
                "address": auth.address,
                "gender": auth.gender,
                "position": auth.position,
                "qualification": auth.qualification,
                "experience_years": auth.experience_years,
                "joining_date": _iso(auth.joining_date),
                "status": auth.status,
                "authority_details": auth.authority_details,
                "permissions": auth.permissions,
                "org_overview": auth.org_overview,
                "contact_info": auth.contact_info,
                "last_login": _iso(auth.last_login),
                "organisation_id": str(auth.organisation_id),
            }

        return None
