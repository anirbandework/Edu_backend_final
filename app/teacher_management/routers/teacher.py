# app/routers/school_authority/teacher.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from ...core.database import get_db
from ...teacher_management.models.teacher import Teacher
from ...teacher_management.services.teacher_service import TeacherService
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_authority, assert_same_tenant
from ...auth_rbac.security.principal import Principal, ROLE_TEACHER
from ...auth_rbac.services import invitation_service

# Existing Pydantic Models
class TeacherCreate(BaseModel):
    tenant_id: UUID
    teacher_id: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    position: str
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    joining_date: Optional[datetime] = None
    role: Optional[str] = "teacher"
    status: Optional[str] = "active"
    qualification: Optional[str] = None
    experience_years: Optional[int] = 0
    teacher_details: Optional[dict] = None
    personal_info: Optional[dict] = None
    contact_info: Optional[dict] = None
    family_info: Optional[dict] = None
    qualifications: Optional[dict] = None
    employment: Optional[dict] = None
    academic_responsibilities: Optional[dict] = None
    timetable: Optional[dict] = None
    performance_evaluation: Optional[dict] = None

class TeacherUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    gender: Optional[str] = None
    position: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    teacher_details: Optional[dict] = None
    personal_info: Optional[dict] = None
    contact_info: Optional[dict] = None
    family_info: Optional[dict] = None
    qualifications: Optional[dict] = None
    employment: Optional[dict] = None
    academic_responsibilities: Optional[dict] = None
    timetable: Optional[dict] = None
    performance_evaluation: Optional[dict] = None
    status: Optional[str] = None

# NEW BULK OPERATION MODELS
class BulkTeacherImport(BaseModel):
    tenant_id: UUID
    teachers: List[dict]

class BulkStatusUpdate(BaseModel):
    tenant_id: UUID
    teacher_uuids: List[UUID] = Field(alias="teacher-uuids")
    new_status: str  # active, inactive, resigned, terminated, on_leave

class SubjectAssignment(BaseModel):
    subject: str
    grade: Optional[str] = None
    section: Optional[str] = None
    hours_per_week: Optional[int] = None

class TeacherSubjectAssignment(BaseModel):
    teacher_uuid: UUID = Field(alias="teacher-uuid")
    subjects: List[SubjectAssignment]

class BulkSubjectAssignment(BaseModel):
    tenant_id: UUID
    assignments: List[TeacherSubjectAssignment]

class SalaryUpdate(BaseModel):
    teacher_uuid: UUID = Field(alias="teacher-uuid")
    basic_salary: float
    allowances: Optional[dict] = None
    effective_date: Optional[datetime] = None
    reason: Optional[str] = None

class BulkSalaryUpdate(BaseModel):
    tenant_id: UUID
    salary_updates: List[SalaryUpdate]

class BulkDeleteRequest(BaseModel):
    tenant_id: UUID
    teacher_uuids: List[UUID] = Field(alias="teacher-uuids")

router = APIRouter(prefix="/api/v1/school_authority/teachers", tags=["School Authority - Teacher Management"])

# EXISTING ENDPOINTS (unchanged)
@router.get("/", response_model=dict)
async def get_teachers(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get paginated teachers with filtering"""
    service = TeacherService(db)

    # Non-super-admins are always scoped to their own tenant; ignore client-supplied tenant_id.
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    try:
        result = await service.get_teachers_paginated(
            page=page,
            size=size,
            tenant_id=effective_tenant
        )
        
        formatted_teachers = [
            {
                "id": str(teacher.id),
                "tenant_id": str(teacher.tenant_id),
                "teacher_id": teacher.teacher_id,
                
                # Use individual fields first, fallback to JSON
                "first_name": teacher.first_name or (teacher.personal_info.get('basic_details', {}).get('first_name', '') if teacher.personal_info else ''),
                "last_name": teacher.last_name or (teacher.personal_info.get('basic_details', {}).get('last_name', '') if teacher.personal_info else ''),
                "email": teacher.email or (teacher.personal_info.get('contact_info', {}).get('primary_email', '') if teacher.personal_info else ''),
                "phone": teacher.phone or (teacher.personal_info.get('contact_info', {}).get('primary_phone', '') if teacher.personal_info else ''),
                "date_of_birth": teacher.date_of_birth.isoformat() if teacher.date_of_birth else None,
                "gender": teacher.gender,
                "address": teacher.address,
                
                # Employment info
                "position": teacher.position or (teacher.employment.get('job_information', {}).get('current_position', '') if teacher.employment else ''),
                "department": (teacher.teacher_details.get('department', '') if teacher.teacher_details else '') or (teacher.employment.get('job_information', {}).get('department', '') if teacher.employment else ''),
                "joining_date": (teacher.joining_date.isoformat() if teacher.joining_date else '') or (teacher.employment.get('job_information', {}).get('joining_date', '') if teacher.employment else ''),
                "role": teacher.role,
                "qualification": teacher.qualification,
                "experience_years": teacher.experience_years,
                
                # JSON fields
                "academic_responsibilities": teacher.academic_responsibilities,
                "teacher_details": teacher.teacher_details,
                
                # Teaching subjects
                "subjects": [assignment.get('subject', '') for assignment in (teacher.academic_responsibilities.get('teaching_assignments', []) if teacher.academic_responsibilities else [])],
                
                "status": teacher.status,
                "last_login": teacher.last_login.isoformat() if teacher.last_login else None,
                "created_at": teacher.created_at.isoformat(),
                "updated_at": teacher.updated_at.isoformat()
            }
            for teacher in result["items"]
        ]
        
        return {
            "items": formatted_teachers,
            "total": result["total"],
            "page": result["page"],
            "size": result["size"],
            "has_next": result["has_next"],
            "has_previous": result["has_previous"],
            "total_pages": result["total_pages"]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=dict)
async def create_teacher(
    teacher_data: TeacherCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Create new teacher"""
    service = TeacherService(db)

    teacher_dict = teacher_data.model_dump()
    # Non-super-admins may only create within their own tenant; override client-supplied tenant_id.
    if not principal.is_super_admin:
        teacher_dict["tenant_id"] = principal.tenant_id
    teacher = await service.create(teacher_dict)

    resp = {
        "id": str(teacher.id),
        "message": "Teacher created successfully",
        "teacher_id": teacher.teacher_id,
        "login_enabled": False,  # no password until the invite is accepted
    }
    # Onboarding: a school authority can immediately issue a signup invite so the new
    # teacher can set their own password and log in. (Super-admins cannot invite teachers,
    # per invitation rules, so the link is only generated for authority creators.)
    if principal.is_authority:
        try:
            inv = await invitation_service.create_invitation(
                db, principal, role=ROLE_TEACHER, target_user_id=str(teacher.id),
                first_name=teacher.first_name, last_name=teacher.last_name, email=teacher.email,
            )
            resp["invitation_link"] = invitation_service.signup_url(inv.token)
        except HTTPException:
            raise
        except Exception:
            # Never fail teacher creation because invite issuance hiccuped; the authority
            # can re-invite from the teacher record later.
            resp["invitation_link"] = None
    return resp

@router.get("/{teacher_id}", response_model=dict)
async def get_teacher(
    teacher_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get specific teacher with complete details"""
    service = TeacherService(db)
    teacher = await service.get(
        teacher_id,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id)
    )

    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    
    return {
        "id": str(teacher.id),
        "tenant_id": str(teacher.tenant_id),
        "teacher_id": teacher.teacher_id,
        "first_name": teacher.first_name,
        "last_name": teacher.last_name,
        "personal_info": teacher.personal_info,
        "contact_info": teacher.contact_info,
        "family_info": teacher.family_info,
        "qualifications": teacher.qualifications,
        "employment": teacher.employment,
        "academic_responsibilities": teacher.academic_responsibilities,
        "timetable": teacher.timetable,
        "performance_evaluation": teacher.performance_evaluation,
        "status": teacher.status,
        "last_login": teacher.last_login.isoformat() if teacher.last_login else None,
        "created_at": teacher.created_at.isoformat(),
        "updated_at": teacher.updated_at.isoformat()
    }

@router.put("/{teacher_id}", response_model=dict)
async def update_teacher(
    teacher_id: UUID,
    teacher_data: TeacherUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Update teacher information"""
    service = TeacherService(db)

    update_dict = teacher_data.model_dump(exclude_unset=True)
    teacher = await service.update(
        teacher_id,
        update_dict,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id)
    )

    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    
    return {
        "id": str(teacher.id),
        "message": "Teacher updated successfully"
    }

@router.delete("/{teacher_id}")
async def delete_teacher(
    teacher_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Soft delete teacher"""
    service = TeacherService(db)
    success = await service.soft_delete(
        teacher_id,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id)
    )

    if not success:
        raise HTTPException(status_code=404, detail="Teacher not found")
    
    return {"message": "Teacher deactivated successfully"}

@router.get("/tenant/{tenant_id}")
async def get_teachers_by_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all teachers for a specific school/tenant"""
    assert_same_tenant(principal, tenant_id)
    service = TeacherService(db)
    teachers = await service.get_by_tenant(tenant_id)
    
    return [
        {
            "id": str(teacher.id),
            "teacher_id": teacher.teacher_id,
            "name": f"{teacher.personal_info.get('basic_details', {}).get('first_name', '')} {teacher.personal_info.get('basic_details', {}).get('last_name', '')}" if teacher.personal_info else "",
            "email": teacher.personal_info.get('contact_info', {}).get('primary_email', '') if teacher.personal_info else '',
            "position": teacher.employment.get('job_information', {}).get('current_position', '') if teacher.employment else '',
            "department": teacher.employment.get('job_information', {}).get('department', '') if teacher.employment else '',
            "status": teacher.status
        }
        for teacher in teachers
    ]

@router.get("/subject/{subject}")
async def get_teachers_by_subject(
    subject: str,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get teachers who teach a specific subject"""
    service = TeacherService(db)
    # Non-super-admins are always scoped to their own tenant; ignore client-supplied tenant_id.
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    teachers = await service.get_teachers_by_subject(subject, effective_tenant)
    
    return [
        {
            "id": str(teacher.id),
            "teacher_id": teacher.teacher_id,
            "name": f"{teacher.personal_info.get('basic_details', {}).get('first_name', '')} {teacher.personal_info.get('basic_details', {}).get('last_name', '')}" if teacher.personal_info else "",
            "email": teacher.personal_info.get('contact_info', {}).get('primary_email', '') if teacher.personal_info else '',
            "department": teacher.employment.get('job_information', {}).get('department', '') if teacher.employment else '',
            "subject": subject,
            "status": teacher.status
        }
        for teacher in teachers
    ]

# NEW BULK OPERATION ENDPOINTS

@router.post("/bulk/import", response_model=dict)
async def bulk_import_teachers(
    import_data: BulkTeacherImport,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk import teachers from CSV/JSON data"""
    service = TeacherService(db)

    # Non-super-admins may only operate within their own tenant; override client-supplied tenant_id.
    if not principal.is_super_admin:
        import_data.tenant_id = principal.tenant_id

    result = await service.bulk_import_teachers(
        teachers_data=import_data.teachers,
        tenant_id=import_data.tenant_id
    )
    
    return {
        "message": f"Bulk import completed. {result['successful_imports']} teachers imported successfully",
        **result
    }

@router.post("/bulk/update-status", response_model=dict)
async def bulk_update_status(
    status_data: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk update teacher status"""
    service = TeacherService(db)

    # Non-super-admins may only operate within their own tenant; override client-supplied tenant_id.
    if not principal.is_super_admin:
        status_data.tenant_id = principal.tenant_id

    result = await service.bulk_update_status(
        teacher_uuids=status_data.teacher_uuids,
        new_status=status_data.new_status,
        tenant_id=status_data.tenant_id
    )
    
    return {
        "message": f"Status update completed. {result['updated_teachers']} teachers updated to '{result['new_status']}'",
        **result
    }

@router.post("/bulk/assign-subjects", response_model=dict)
async def bulk_assign_subjects(
    assignment_data: BulkSubjectAssignment,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk assign subjects to teachers"""
    service = TeacherService(db)

    # Non-super-admins may only operate within their own tenant; override client-supplied tenant_id.
    if not principal.is_super_admin:
        assignment_data.tenant_id = principal.tenant_id

    result = await service.bulk_assign_subjects(
        subject_assignments=[assignment.model_dump(by_alias=True) for assignment in assignment_data.assignments],
        tenant_id=assignment_data.tenant_id
    )
    
    return {
        "message": f"Subject assignment completed. {result['updated_teachers']} teachers updated",
        **result
    }

@router.post("/bulk/update-salaries", response_model=dict)
async def bulk_update_salaries(
    salary_data: BulkSalaryUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk update teacher salaries"""
    service = TeacherService(db)

    # Non-super-admins may only operate within their own tenant; override client-supplied tenant_id.
    if not principal.is_super_admin:
        salary_data.tenant_id = principal.tenant_id

    result = await service.bulk_salary_update(
        salary_updates=[update.model_dump(by_alias=True) for update in salary_data.salary_updates],
        tenant_id=salary_data.tenant_id
    )
    
    return {
        "message": f"Salary update completed. {result['updated_teachers']} teachers updated",
        **result
    }

@router.post("/bulk/delete", response_model=dict)
async def bulk_delete_teachers(
    delete_data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk soft delete teachers"""
    service = TeacherService(db)

    # Non-super-admins may only operate within their own tenant; override client-supplied tenant_id.
    if not principal.is_super_admin:
        delete_data.tenant_id = principal.tenant_id

    result = await service.bulk_soft_delete(
        teacher_uuids=delete_data.teacher_uuids,
        tenant_id=delete_data.tenant_id
    )
    
    return {
        "message": f"Bulk delete completed. {result['deleted_teachers']} teachers deactivated",
        **result
    }

@router.get("/statistics/{tenant_id}", response_model=dict)
async def get_teacher_statistics(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get comprehensive teacher statistics for a school"""
    assert_same_tenant(principal, tenant_id)
    service = TeacherService(db)

    stats = await service.get_teacher_statistics(tenant_id)
    
    return {
        "message": "Teacher statistics retrieved successfully",
        **stats
    }
