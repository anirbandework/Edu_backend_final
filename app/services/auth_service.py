from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, and_
from typing import Optional
from uuid import UUID

from ..models.role_management import Role, UserRole, PagePermission
from ..models.tenant_specific.school_authority import SchoolAuthority
from ..models.tenant_specific.teacher import Teacher
from ..models.tenant_specific.student import Student

class AuthService:
    
    @staticmethod
    async def get_user_profile(db: AsyncSession, user_id: UUID, tenant_id: UUID = None) -> Optional[dict]:
        """Get complete user profile with roles for login"""
        
        # Check school authority first
        query = select(SchoolAuthority).where(SchoolAuthority.id == user_id)
        if tenant_id:
            query = query.where(SchoolAuthority.tenant_id == tenant_id)
        
        auth_result = await db.execute(query)
        auth = auth_result.scalar_one_or_none()
        if auth:
            user_role = await db.execute(
                select(UserRole).options(selectinload(UserRole.role)).where(
                    and_(UserRole.user_id == user_id, UserRole.role.has(Role.is_active == True))
                )
            )
            role_data = user_role.scalar_one_or_none()
            role_info = {
                "role_name": role_data.role.role_name,
                "subrole": role_data.role.subrole,
                "description": role_data.role.description
            } if role_data else None
            
            # Get user's page permissions based on auth_role
            page_permissions = []
            if role_data:  # User has auth_role assigned
                permissions_result = await db.execute(
                    select(PagePermission).where(
                        and_(
                            PagePermission.tenant_id == auth.tenant_id,
                            PagePermission.role_id == role_data.role_id,
                            PagePermission.is_active == True
                        )
                    )
                )
                page_permissions = [{
                    "page_id": p.page_id,
                    "page_name": p.page_name,
                    "page_path": p.page_path,
                    "page_icon": p.page_icon,
                    "page_category": p.page_category,
                    "permissions": {
                        "can_view": p.can_view,
                        "can_create": p.can_create,
                        "can_edit": p.can_edit,
                        "can_delete": p.can_delete,
                        "can_export": p.can_export,
                        "can_import": p.can_import,
                        "custom": p.custom_permissions
                    }
                } for p in permissions_result.scalars().all()]
            else:  # No auth_role - only show profile page
                page_permissions = [{
                    "page_id": "profile",
                    "page_name": "Profile",
                    "page_path": "/profile",
                    "page_icon": "person",
                    "page_category": "Personal",
                    "permissions": {
                        "can_view": True,
                        "can_create": False,
                        "can_edit": True,
                        "can_delete": False,
                        "can_export": False,
                        "can_import": False,
                        "custom": {}
                    }
                }]
            
            return {
                "user_id": str(auth.id),
                "user_type": "SCHOOL_AUTHORITY",
                "role": "admin",  # For frontend navigation
                "authority_id": auth.authority_id,
                "first_name": auth.first_name,
                "last_name": auth.last_name,
                "email": auth.email,
                "phone": auth.phone,
                "date_of_birth": auth.date_of_birth.isoformat() if auth.date_of_birth else None,
                "address": auth.address,
                "gender": auth.gender,
                "position": auth.position,
                "qualification": auth.qualification,
                "experience_years": auth.experience_years,
                "joining_date": auth.joining_date.isoformat() if auth.joining_date else None,
                "status": auth.status,
                "authority_details": auth.authority_details,
                "permissions": auth.permissions,
                "school_overview": auth.school_overview,
                "contact_info": auth.contact_info,
                "last_login": auth.last_login.isoformat() if auth.last_login else None,
                "tenant_id": str(auth.tenant_id),
                "auth_role": role_info,
                "page_permissions": page_permissions
            }
        
        # Check teacher
        query = select(Teacher).where(Teacher.id == user_id)
        if tenant_id:
            query = query.where(Teacher.tenant_id == tenant_id)
            
        teacher_result = await db.execute(query)
        teacher = teacher_result.scalar_one_or_none()
        if teacher:
            user_role = await db.execute(
                select(UserRole).options(selectinload(UserRole.role)).where(
                    and_(UserRole.user_id == user_id, UserRole.role.has(Role.is_active == True))
                )
            )
            role_data = user_role.scalar_one_or_none()
            role_info = {
                "role_name": role_data.role.role_name,
                "subrole": role_data.role.subrole,
                "description": role_data.role.description
            } if role_data else None
            
            # Get user's page permissions based on auth_role
            page_permissions = []
            if role_data:  # User has auth_role assigned
                permissions_result = await db.execute(
                    select(PagePermission).where(
                        and_(
                            PagePermission.tenant_id == teacher.tenant_id,
                            PagePermission.role_id == role_data.role_id,
                            PagePermission.is_active == True
                        )
                    )
                )
                page_permissions = [{
                    "page_id": p.page_id,
                    "page_name": p.page_name,
                    "page_path": p.page_path,
                    "page_icon": p.page_icon,
                    "page_category": p.page_category,
                    "permissions": {
                        "can_view": p.can_view,
                        "can_create": p.can_create,
                        "can_edit": p.can_edit,
                        "can_delete": p.can_delete,
                        "can_export": p.can_export,
                        "can_import": p.can_import,
                        "custom": p.custom_permissions
                    }
                } for p in permissions_result.scalars().all()]
            else:  # No auth_role - only show profile page
                page_permissions = [{
                    "page_id": "profile",
                    "page_name": "Profile",
                    "page_path": "/profile",
                    "page_icon": "person",
                    "page_category": "Personal",
                    "permissions": {
                        "can_view": True,
                        "can_create": False,
                        "can_edit": True,
                        "can_delete": False,
                        "can_export": False,
                        "can_import": False,
                        "custom": {}
                    }
                }]
            
            return {
                "user_id": str(teacher.id),
                "user_type": "TEACHER",
                "role": "teacher",  # For frontend navigation
                "teacher_id": teacher.teacher_id,
                "first_name": teacher.first_name,
                "last_name": teacher.last_name,
                "email": teacher.email,
                "phone": teacher.phone,
                "date_of_birth": teacher.date_of_birth.isoformat() if teacher.date_of_birth else None,
                "address": teacher.address,
                "gender": teacher.gender,
                "position": teacher.position,
                "qualification": teacher.qualification,
                "experience_years": teacher.experience_years,
                "joining_date": teacher.joining_date.isoformat() if teacher.joining_date else None,
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
                "last_login": teacher.last_login.isoformat() if teacher.last_login else None,
                "tenant_id": str(teacher.tenant_id),
                "auth_role": role_info,
                "page_permissions": page_permissions
            }
        
        # Check student
        query = select(Student).where(Student.id == user_id)
        if tenant_id:
            query = query.where(Student.tenant_id == tenant_id)
            
        student_result = await db.execute(query)
        student = student_result.scalar_one_or_none()
        if student:
            user_role = await db.execute(
                select(UserRole).options(selectinload(UserRole.role)).where(
                    and_(UserRole.user_id == user_id, UserRole.role.has(Role.is_active == True))
                )
            )
            role_data = user_role.scalar_one_or_none()
            role_info = {
                "role_name": role_data.role.role_name,
                "subrole": role_data.role.subrole,
                "description": role_data.role.description
            } if role_data else None
            
            # Get user's page permissions based on auth_role
            page_permissions = []
            if role_data:  # User has auth_role assigned
                permissions_result = await db.execute(
                    select(PagePermission).where(
                        and_(
                            PagePermission.tenant_id == student.tenant_id,
                            PagePermission.role_id == role_data.role_id,
                            PagePermission.is_active == True
                        )
                    )
                )
                page_permissions = [{
                    "page_id": p.page_id,
                    "page_name": p.page_name,
                    "page_path": p.page_path,
                    "page_icon": p.page_icon,
                    "page_category": p.page_category,
                    "permissions": {
                        "can_view": p.can_view,
                        "can_create": p.can_create,
                        "can_edit": p.can_edit,
                        "can_delete": p.can_delete,
                        "can_export": p.can_export,
                        "can_import": p.can_import,
                        "custom": p.custom_permissions
                    }
                } for p in permissions_result.scalars().all()]
            else:  # No auth_role - only show profile page
                page_permissions = [{
                    "page_id": "profile",
                    "page_name": "Profile",
                    "page_path": "/profile",
                    "page_icon": "person",
                    "page_category": "Personal",
                    "permissions": {
                        "can_view": True,
                        "can_create": False,
                        "can_edit": True,
                        "can_delete": False,
                        "can_export": False,
                        "can_import": False,
                        "custom": {}
                    }
                }]
            
            return {
                "user_id": str(student.id),
                "user_type": "STUDENT",
                "role": "student",  # For frontend navigation
                "student_id": student.student_id,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "email": student.email,
                "phone": student.phone,
                "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else None,
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
                "last_login": student.last_login.isoformat() if student.last_login else None,
                "tenant_id": str(student.tenant_id),
                "auth_role": role_info,
                "page_permissions": page_permissions
            }
        
        return None