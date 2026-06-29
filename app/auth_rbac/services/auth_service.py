"""User profile lookup for GET /api/auth/user-profile/{user_id}.

Identity-only: returns the user's own record across the three identity tables.
Module/tab permissions are served separately by /api/access/my-permissions, so this
no longer depends on the retired page-based RBAC tables (Role/UserRole/PagePermission/
TenantPageAccess).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import UUID

from ...school_authority_management.models.school_authority import SchoolAuthority
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
            "school_authority": SchoolAuthority,
            "staff": Member,
        }.get(role)
        if not model:
            return None
        return (await db.execute(select(model).where(model.id == user_id))).scalar_one_or_none()

    @staticmethod
    async def get_user_profile(db: AsyncSession, user_id: UUID, tenant_id: UUID = None) -> Optional[dict]:
        """Return the identity profile for a user, searching every identity table
        (super-admin, school authority, staff, teacher, student)."""
        # Super-admin (platform owner; no tenant)
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
                "tenant_id": None,
            }

        # Unified dynamic-role staff
        q = select(Member).where(Member.id == user_id)
        if tenant_id:
            q = q.where(Member.tenant_id == tenant_id)
        staff = (await db.execute(q)).scalar_one_or_none()
        if staff:
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
                "last_login": _iso(staff.last_login),
                "tenant_id": str(staff.tenant_id) if staff.tenant_id else None,
            }

        # School authority
        q = select(SchoolAuthority).where(SchoolAuthority.id == user_id)
        if tenant_id:
            q = q.where(SchoolAuthority.tenant_id == tenant_id)
        auth = (await db.execute(q)).scalar_one_or_none()
        if auth:
            return {
                "user_id": str(auth.id),
                "user_type": "SCHOOL_AUTHORITY",
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
                "school_overview": auth.school_overview,
                "contact_info": auth.contact_info,
                "last_login": _iso(auth.last_login),
                "tenant_id": str(auth.tenant_id),
            }

        # Any non-authority user is a Member (dynamic model). profile.category marks a
        # "student" member; legacy teacher/student extras live in members.profile JSON.
        q = select(Member).where(Member.id == user_id)
        if tenant_id:
            q = q.where(Member.tenant_id == tenant_id)
        member = (await db.execute(q)).scalar_one_or_none()
        if member:
            prof = member.profile or {}
            is_student = prof.get("category") == "student"
            return {
                "user_id": str(member.id),
                "user_type": "STUDENT" if is_student else "STAFF",
                "role": "student" if is_student else "staff",
                "staff_id": member.staff_id,
                "student_id": member.staff_id,
                "teacher_id": member.staff_id,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "email": member.email,
                "phone": member.phone,
                "date_of_birth": _iso(member.date_of_birth),
                "address": member.address,
                "gender": member.gender,
                "position": member.position,
                "status": member.status,
                "rbac_role_id": str(member.rbac_role_id) if member.rbac_role_id else None,
                "roll_number": prof.get("roll_number"),
                "admission_number": prof.get("admission_number"),
                "grade_level": prof.get("grade_level"),
                "section": prof.get("section"),
                "academic_year": prof.get("academic_year"),
                "parent_info": prof.get("parent_info"),
                "profile": prof,
                "last_login": _iso(member.last_login),
                "tenant_id": str(member.tenant_id),
            }

        return None
