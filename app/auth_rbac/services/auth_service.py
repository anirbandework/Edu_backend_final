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
from ...teacher_management.models.teacher import Teacher
from ...student_management.models.student import Student
from ...staff_management.models.staff_user import StaffUser


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
            "staff": StaffUser,
            "teacher": Teacher,
            "student": Student,
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
        q = select(StaffUser).where(StaffUser.id == user_id)
        if tenant_id:
            q = q.where(StaffUser.tenant_id == tenant_id)
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

        # Teacher
        q = select(Teacher).where(Teacher.id == user_id)
        if tenant_id:
            q = q.where(Teacher.tenant_id == tenant_id)
        teacher = (await db.execute(q)).scalar_one_or_none()
        if teacher:
            return {
                "user_id": str(teacher.id),
                "user_type": "TEACHER",
                "role": "teacher",
                "teacher_id": teacher.teacher_id,
                "first_name": teacher.first_name,
                "last_name": teacher.last_name,
                "email": teacher.email,
                "phone": teacher.phone,
                "date_of_birth": _iso(teacher.date_of_birth),
                "address": teacher.address,
                "gender": teacher.gender,
                "position": teacher.position,
                "qualification": teacher.qualification,
                "experience_years": teacher.experience_years,
                "joining_date": _iso(teacher.joining_date),
                "status": teacher.status,
                "teacher_details": teacher.teacher_details,
                "personal_info": teacher.personal_info,
                "contact_info": teacher.contact_info,
                "family_info": teacher.family_info,
                "qualifications": teacher.qualifications,
                "employment": teacher.employment,
                "academic_responsibilities": teacher.academic_responsibilities,
                "timetable": teacher.timetable,
                "performance_evaluation": teacher.performance_evaluation,
                "last_login": _iso(teacher.last_login),
                "tenant_id": str(teacher.tenant_id),
            }

        # Student
        q = select(Student).where(Student.id == user_id)
        if tenant_id:
            q = q.where(Student.tenant_id == tenant_id)
        student = (await db.execute(q)).scalar_one_or_none()
        if student:
            return {
                "user_id": str(student.id),
                "user_type": "STUDENT",
                "role": "student",
                "student_id": student.student_id,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "email": student.email,
                "phone": student.phone,
                "date_of_birth": _iso(student.date_of_birth),
                "address": student.address,
                "gender": student.gender,
                "admission_number": student.admission_number,
                "roll_number": student.roll_number,
                "grade_level": student.grade_level,
                "section": student.section,
                "academic_year": student.academic_year,
                "status": student.status,
                "parent_info": student.parent_info,
                "health_medical_info": student.health_medical_info,
                "emergency_information": student.emergency_information,
                "behavioral_disciplinary": student.behavioral_disciplinary,
                "extended_academic_info": student.extended_academic_info,
                "enrollment_details": student.enrollment_details,
                "financial_info": student.financial_info,
                "extracurricular_social": student.extracurricular_social,
                "attendance_engagement": student.attendance_engagement,
                "additional_metadata": student.additional_metadata,
                "last_login": _iso(student.last_login),
                "tenant_id": str(student.tenant_id),
            }

        return None
