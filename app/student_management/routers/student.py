# app/routers/school_authority/student.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime
from ...core.database import get_db
from ...student_management.models.student import Student
from ...enrollment_management.models.enrollment import Enrollment
from ...class_management.models.class_model import ClassModel
from ...student_management.services.student_service import StudentService
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_authority, assert_same_tenant
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal, ROLE_STUDENT
from ...auth_rbac.services import invitation_service

# Pydantic Models
class StudentCreate(BaseModel):
    tenant_id: UUID
    student_id: str
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    address: Optional[str] = None
    admission_number: Optional[str] = None
    roll_number: Optional[str] = None
    grade_level: Optional[int] = None
    section: Optional[str] = None
    academic_year: Optional[str] = None
    status: Optional[str] = "active"
    parent_info: Optional[dict] = None
    health_medical_info: Optional[dict] = None
    emergency_information: Optional[dict] = None
    behavioral_disciplinary: Optional[dict] = None
    extended_academic_info: Optional[dict] = None
    enrollment_details: Optional[dict] = None
    financial_info: Optional[dict] = None
    extracurricular_social: Optional[dict] = None
    attendance_engagement: Optional[dict] = None
    additional_metadata: Optional[dict] = None
    
    @field_validator('date_of_birth')
    @classmethod
    def convert_datetime_to_naive(cls, v):
        if v and v.tzinfo is not None:
            return v.replace(tzinfo=None)
        return v

class StudentUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    roll_number: Optional[str] = None
    grade_level: Optional[int] = None
    section: Optional[str] = None
    academic_year: Optional[str] = None
    status: Optional[str] = None
    parent_info: Optional[dict] = None
    health_medical_info: Optional[dict] = None
    emergency_information: Optional[dict] = None
    behavioral_disciplinary: Optional[dict] = None
    extended_academic_info: Optional[dict] = None
    enrollment_details: Optional[dict] = None
    financial_info: Optional[dict] = None
    extracurricular_social: Optional[dict] = None
    attendance_engagement: Optional[dict] = None
    additional_metadata: Optional[dict] = None

# NEW BULK OPERATION MODELS
class BulkStudentImport(BaseModel):
    tenant_id: UUID
    students: List[dict]  # List of student data dictionaries

class BulkGradeUpdate(BaseModel):
    tenant_id: UUID
    grade_updates: List[dict]  # [{"student_id": "STU001", "new_grade": 11}]

class BulkStatusUpdate(BaseModel):
    tenant_id: UUID
    student_ids: List[str]
    new_status: str

class BulkSectionUpdate(BaseModel):
    tenant_id: UUID
    section_updates: List[dict]  # [{"student_id": "STU001", "new_section": "B"}]

class BulkDeleteRequest(BaseModel):
    tenant_id: UUID
    student_ids: List[str]

class BulkPromotionRequest(BaseModel):
    tenant_id: UUID
    current_grade: int
    academic_year: str

router = APIRouter(prefix="/api/v1/school_authority/students", tags=["School Authority - Student Management"])

# EXISTING ENDPOINTS (unchanged)
@router.get("/", response_model=dict)
async def get_students(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: Optional[UUID] = Query(None),
    grade_level: Optional[int] = Query(None),
    section: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get paginated students with filtering"""
    service = StudentService(db)

    # Enforce tenant scoping: non-super-admins are locked to their own tenant
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    try:
        result = await service.get_students_paginated(
            page=page,
            size=size,
            tenant_id=effective_tenant,
            grade_level=grade_level,
            section=section
        )
        
        # Format student data with full JSON fields
        formatted_students = [
            {
                "id": str(student.id),
                "tenant_id": str(student.tenant_id),
                "student_id": student.student_id,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "email": student.email,
                "phone": student.phone,
                "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else None,
                "address": student.address,
                "grade_level": student.grade_level,
                "section": student.section,
                "admission_number": student.admission_number,
                "roll_number": student.roll_number,
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
                "created_at": student.created_at.isoformat(),
                "updated_at": student.updated_at.isoformat()
            }
            for student in result["items"]
        ]
        
        return {
            "items": formatted_students,
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
async def create_student(
    student_data: StudentCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Create new student"""
    service = StudentService(db)

    student_dict = student_data.model_dump()
    # Non-super-admins may only create within their own tenant; override any client value
    if not principal.is_super_admin:
        student_dict["tenant_id"] = principal.tenant_id
    student = await service.create(student_dict)

    resp = {
        "id": str(student.id),
        "message": "Student created successfully",
        "student_id": student.student_id,
        "admission_number": student.admission_number,
        "login_enabled": False,  # no password until the invite is accepted
    }
    # Onboarding: a school authority can immediately issue a signup invite so the new
    # student (or parent) can set a password and log in. Super-admins can't invite students.
    if principal.is_authority:
        try:
            inv = await invitation_service.create_invitation(
                db, principal, role=ROLE_STUDENT, target_user_id=str(student.id),
                first_name=student.first_name, last_name=student.last_name, email=student.email,
            )
            resp["invitation_link"] = invitation_service.signup_url(inv.token)
        except HTTPException:
            raise
        except Exception:
            resp["invitation_link"] = None
    return resp

@router.get("/{student_id}", response_model=dict)
async def get_student(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get specific student with complete details"""
    service = StudentService(db)
    scope_tenant = None if principal.is_super_admin else principal.tenant_id
    student = await service.get(student_id, tenant_id=scope_tenant)

    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    return {
        "id": str(student.id),
        "tenant_id": str(student.tenant_id),
        "student_id": student.student_id,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "email": student.email,
        "phone": student.phone,
        "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else None,
        "address": student.address,
        "role": student.role,
        "status": student.status,
        "admission_number": student.admission_number,
        "roll_number": student.roll_number,
        "grade_level": student.grade_level,
        "section": student.section,
        "academic_year": student.academic_year,
        
        # Extended information from JSON fields
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
        "created_at": student.created_at.isoformat(),
        "updated_at": student.updated_at.isoformat()
    }

@router.put("/{student_id}", response_model=dict)
async def update_student(
    student_id: UUID,
    student_data: StudentUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Update student information"""
    service = StudentService(db)

    update_dict = student_data.model_dump(exclude_unset=True)
    scope_tenant = None if principal.is_super_admin else principal.tenant_id
    student = await service.update(student_id, update_dict, tenant_id=scope_tenant)

    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    return {
        "id": str(student.id),
        "message": "Student updated successfully"
    }

@router.delete("/{student_id}")
async def delete_student(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Soft delete student"""
    service = StudentService(db)
    scope_tenant = None if principal.is_super_admin else principal.tenant_id
    success = await service.soft_delete(student_id, tenant_id=scope_tenant)

    if not success:
        raise HTTPException(status_code=404, detail="Student not found")
    
    return {"message": "Student deactivated successfully"}

@router.get("/tenant/{tenant_id}")
async def get_students_by_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all students for a specific school/tenant"""
    # Non-super-admins may only read their own tenant
    assert_same_tenant(principal, tenant_id)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)
    students = await service.get_by_tenant(effective_tenant)
    
    return [
        {
            "id": str(student.id),
            "student_id": student.student_id,
            "name": f"{student.first_name} {student.last_name}",
            "email": student.email,
            "grade_level": student.grade_level,
            "section": student.section,
            "admission_number": student.admission_number,
            "status": student.status
        }
        for student in students
    ]

@router.get("/{student_id}/classes", response_model=dict)
async def get_student_classes(
    student_id: UUID,
    academic_year: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all classes that a student belongs to"""
    from sqlalchemy import select

    # Verify student exists
    student_stmt = select(Student).where(Student.id == student_id, Student.is_deleted == False)
    if not principal.is_super_admin:
        student_stmt = student_stmt.where(Student.tenant_id == principal.tenant_id)
    student_result = await db.execute(student_stmt)
    student = student_result.scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Get classes the student is enrolled in
    classes_stmt = (
        select(ClassModel, Enrollment)
        .join(Enrollment, ClassModel.id == Enrollment.class_id)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
            ClassModel.is_deleted == False,
            Enrollment.is_deleted == False
        )
    )
    
    if academic_year:
        classes_stmt = classes_stmt.where(Enrollment.academic_year == academic_year)
    
    classes_stmt = classes_stmt.order_by(ClassModel.grade_level, ClassModel.section)
    
    result = await db.execute(classes_stmt)
    class_enrollments = result.all()
    
    classes_data = [
        {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "academic_year": class_obj.academic_year,
            "classroom": class_obj.classroom,
            "maximum_students": class_obj.maximum_students,
            "current_students": class_obj.current_students,
            "enrollment_date": enrollment.enrollment_date.isoformat() if enrollment.enrollment_date else None,
            "enrollment_status": enrollment.status
        }
        for class_obj, enrollment in class_enrollments
    ]
    
    return {
        "student_info": {
            "id": str(student.id),
            "student_id": student.student_id,
            "first_name": student.first_name,
            "last_name": student.last_name,
            "full_name": f"{student.first_name} {student.last_name}",
            "grade_level": student.grade_level,
            "section": student.section,
            "academic_year": student.academic_year
        },
        "classes": classes_data,
        "total_classes": len(classes_data)
    }

@router.get("/{tenant_id}/grade/{grade_level}")
async def get_students_by_tenant_and_grade(
    tenant_id: UUID,
    grade_level: int,
    section: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get students by tenant and grade level"""
    assert_same_tenant(principal, tenant_id)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)
    students = await service.get_students_by_grade(grade_level, effective_tenant)
    
    # Filter by section if provided
    if section:
        students = [s for s in students if s.section == section]
    
    return {
        "students": [
            {
                "id": str(student.id),
                "student_id": student.student_id,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "full_name": f"{student.first_name} {student.last_name}",
                "email": student.email,
                "section": student.section,
                "roll_number": student.roll_number,
                "grade_level": student.grade_level,
                "status": student.status
            }
            for student in students
        ],
        "total": len(students)
    }

@router.get("/grade/{grade_level}")
async def get_students_by_grade(
    grade_level: int,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get students by grade level"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)
    students = await service.get_students_by_grade(grade_level, effective_tenant)
    
    return [
        {
            "id": str(student.id),
            "student_id": student.student_id,
            "name": f"{student.first_name} {student.last_name}",
            "email": student.email,
            "section": student.section,
            "roll_number": student.roll_number,
            "status": student.status
        }
        for student in students
    ]

# NEW BULK OPERATION ENDPOINTS

@router.post("/bulk/import", response_model=dict)
async def bulk_import_students(
    import_data: BulkStudentImport,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Bulk import students from CSV/JSON data"""
    assert_same_tenant(principal, import_data.tenant_id)
    effective_tenant = import_data.tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    result = await service.bulk_import_students(
        students_data=import_data.students,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Bulk import completed. {result['successful_imports']} students imported successfully",
        **result
    }

@router.post("/bulk/update-grades", response_model=dict)
async def bulk_update_grades(
    grade_data: BulkGradeUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Bulk update student grades"""
    assert_same_tenant(principal, grade_data.tenant_id)
    effective_tenant = grade_data.tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    result = await service.bulk_update_grades(
        grade_updates=grade_data.grade_updates,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Bulk grade update completed. {result['updated_students']} students updated",
        **result
    }

@router.post("/bulk/promote", response_model=dict)
async def bulk_promote_students(
    promotion_data: BulkPromotionRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Promote all students from current grade to next grade"""
    assert_same_tenant(principal, promotion_data.tenant_id)
    effective_tenant = promotion_data.tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    result = await service.bulk_promote_students(
        current_grade=promotion_data.current_grade,
        tenant_id=effective_tenant,
        academic_year=promotion_data.academic_year
    )
    
    return {
        "message": f"Promotion completed. {result['promoted_students']} students promoted from grade {result['from_grade']} to {result['to_grade']}",
        **result
    }

@router.post("/bulk/update-status", response_model=dict)
async def bulk_update_status(
    status_data: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Bulk update student status"""
    assert_same_tenant(principal, status_data.tenant_id)
    effective_tenant = status_data.tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    result = await service.bulk_update_status(
        student_ids=status_data.student_ids,
        new_status=status_data.new_status,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Status update completed. {result['updated_students']} students updated to '{result['new_status']}'",
        **result
    }

@router.post("/bulk/update-sections", response_model=dict)
async def bulk_update_sections(
    section_data: BulkSectionUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Bulk update student sections"""
    assert_same_tenant(principal, section_data.tenant_id)
    effective_tenant = section_data.tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    result = await service.bulk_update_sections(
        section_updates=section_data.section_updates,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Section update completed. {result['updated_students']} students updated",
        **result
    }

@router.post("/bulk/delete", response_model=dict)
async def bulk_delete_students(
    delete_data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('students'))  # writes: authority/super-admin only
):
    """Bulk soft delete students"""
    assert_same_tenant(principal, delete_data.tenant_id)
    effective_tenant = delete_data.tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    result = await service.bulk_soft_delete(
        student_ids=delete_data.student_ids,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Bulk delete completed. {result['deleted_students']} students deactivated",
        **result
    }

@router.get("/statistics/{tenant_id}", response_model=dict)
async def get_student_statistics(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get comprehensive student statistics for a school"""
    assert_same_tenant(principal, tenant_id)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    stats = await service.get_student_statistics(effective_tenant)
    
    return {
        "message": "Student statistics retrieved successfully",
        **stats
    }

# ADDITIONAL UTILITY ENDPOINTS

@router.get("/export/{tenant_id}")
async def export_students(
    tenant_id: UUID,
    format: str = Query("json", enum=["json", "csv"]),
    grade_level: Optional[int] = Query(None),
    section: Optional[str] = Query(None),
    status: Optional[str] = Query("active"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Export student data in JSON or CSV format"""
    assert_same_tenant(principal, tenant_id)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = StudentService(db)

    try:
        # Get filtered students
        filters = {"tenant_id": effective_tenant}
        if grade_level:
            filters["grade_level"] = grade_level
        if section:
            filters["section"] = section
        if status:
            filters["status"] = status
        
        result = await service.get_paginated(page=1, size=10000, **filters)
        students = result["items"]
        
        if format == "csv":
            # Return CSV format headers for frontend processing
            return {
                "format": "csv",
                "headers": [
                    "student_id", "first_name", "last_name", "email", "phone",
                    "grade_level", "section", "admission_number", "academic_year", "status"
                ],
                "data": [
                    [
                        student.student_id, student.first_name, student.last_name,
                        student.email or "", student.phone or "",
                        student.grade_level, student.section or "",
                        student.admission_number, student.academic_year, student.status
                    ]
                    for student in students
                ],
                "total_exported": len(students)
            }
        else:
            # JSON format
            return {
                "format": "json",
                "students": [
                    {
                        "id": str(student.id),
                        "student_id": student.student_id,
                        "first_name": student.first_name,
                        "last_name": student.last_name,
                        "email": student.email,
                        "phone": student.phone,
                        "grade_level": student.grade_level,
                        "section": student.section,
                        "admission_number": student.admission_number,
                        "academic_year": student.academic_year,
                        "status": student.status,
                        "created_at": student.created_at.isoformat()
                    }
                    for student in students
                ],
                "total_exported": len(students)
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
