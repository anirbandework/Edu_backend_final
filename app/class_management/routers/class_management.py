# app/routers/school_authority/class_management.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from ...core.database import get_db
from ...class_management.models.class_model import ClassModel
from ...enrollment_management.models.enrollment import Enrollment
from ...staff_management.models.member import Member
from ...class_management.services.class_service import ClassService
from ...enrollment_management.services.enrollment_service import EnrollmentService
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_authority, assert_same_tenant
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal

# Existing Pydantic Models
class ClassCreate(BaseModel):
    tenant_id: UUID
    class_name: str
    grade_level: int
    section: str
    academic_year: str
    maximum_students: int = 40
    classroom: Optional[str] = None
    is_active: bool = True

class ClassUpdate(BaseModel):
    class_name: Optional[str] = None
    grade_level: Optional[int] = None
    section: Optional[str] = None
    academic_year: Optional[str] = None
    maximum_students: Optional[int] = None
    current_students: Optional[int] = None
    classroom: Optional[str] = None
    is_active: Optional[bool] = None

class StudentCountUpdate(BaseModel):
    current_students: int

# NEW BULK OPERATION MODELS
class BulkClassImport(BaseModel):
    tenant_id: UUID
    classes: List[dict]

class BulkCapacityUpdate(BaseModel):
    tenant_id: UUID
    capacity_updates: List[dict]  # [{"class_id": UUID, "maximum_students": int, "current_students": int}]

class BulkStatusUpdate(BaseModel):
    tenant_id: UUID
    class_ids: List[UUID]
    is_active: bool

class BulkClassroomAssignment(BaseModel):
    tenant_id: UUID
    classroom_assignments: List[dict]  # [{"class_id": UUID, "classroom": str}]

class AcademicYearRollover(BaseModel):
    tenant_id: UUID
    current_year: str
    new_year: str

class BulkDeleteRequest(BaseModel):
    tenant_id: UUID
    class_ids: List[UUID]

class AddStudentsToClass(BaseModel):
    member_ids: List[UUID]
    academic_year: str

class AssignTeachersToClass(BaseModel):
    member_ids: List[UUID]
    subject_name: str

router = APIRouter(prefix="/api/v1/school_authority/classes", tags=["School Authority - Class Management"])

# EXISTING ENDPOINTS (unchanged)
@router.get("/", response_model=dict)
async def get_classes(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: Optional[UUID] = Query(None),
    grade_level: Optional[int] = Query(None),
    section: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get paginated classes with filtering options"""
    service = ClassService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    try:
        result = await service.get_classes_paginated(
            page=page,
            size=size,
            tenant_id=effective_tenant,
            grade_level=grade_level,
            section=section,
            academic_year=academic_year,
            active_only=is_active or False
        )
        
        formatted_classes = [
            {
                "id": str(class_obj.id),
                "tenant_id": str(class_obj.tenant_id),
                "class_name": class_obj.class_name,
                "grade_level": class_obj.grade_level,
                "section": class_obj.section,
                "academic_year": class_obj.academic_year,
                "maximum_students": class_obj.maximum_students,
                "current_students": class_obj.current_students,
                "available_spots": class_obj.maximum_students - class_obj.current_students,
                "classroom": class_obj.classroom,
                "is_active": class_obj.is_active,
                "occupancy_rate": round((class_obj.current_students / class_obj.maximum_students * 100), 2) if class_obj.maximum_students > 0 else 0,
                "created_at": class_obj.created_at.isoformat(),
                "updated_at": class_obj.updated_at.isoformat()
            }
            for class_obj in result["items"]
        ]
        
        return {
            "items": formatted_classes,
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
async def create_class(
    class_data: ClassCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Create new class"""
    service = ClassService(db)

    class_dict = class_data.model_dump()
    # Override client-supplied tenant_id for non-super-admins
    if not principal.is_super_admin:
        class_dict["tenant_id"] = principal.tenant_id
    # Auto-set current_students to 0 for new classes
    class_dict["current_students"] = 0
    class_obj = await service.create(class_dict)
    
    return {
        "id": str(class_obj.id),
        "message": "Class created successfully",
        "class_name": class_obj.class_name,
        "grade_level": class_obj.grade_level,
        "section": class_obj.section
    }

@router.get("/{class_id}", response_model=dict)
async def get_class(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get specific class with complete details"""
    service = ClassService(db)
    class_obj = await service.get(class_id, tenant_id=(None if principal.is_super_admin else principal.tenant_id))

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")
    
    return {
        "id": str(class_obj.id),
        "tenant_id": str(class_obj.tenant_id),
        "class_name": class_obj.class_name,
        "grade_level": class_obj.grade_level,
        "section": class_obj.section,
        "academic_year": class_obj.academic_year,
        "maximum_students": class_obj.maximum_students,
        "current_students": class_obj.current_students,
        "available_spots": class_obj.maximum_students - class_obj.current_students,
        "classroom": class_obj.classroom,
        "is_active": class_obj.is_active,
        "occupancy_rate": round((class_obj.current_students / class_obj.maximum_students * 100), 2) if class_obj.maximum_students > 0 else 0,
        "created_at": class_obj.created_at.isoformat(),
        "updated_at": class_obj.updated_at.isoformat()
    }

@router.put("/{class_id}", response_model=dict)
async def update_class(
    class_id: UUID,
    class_data: ClassUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Update class information"""
    service = ClassService(db)

    update_dict = class_data.model_dump(exclude_unset=True)
    class_obj = await service.update(class_id, update_dict, tenant_id=(None if principal.is_super_admin else principal.tenant_id))

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")
    
    return {
        "id": str(class_obj.id),
        "message": "Class updated successfully",
        "class_name": class_obj.class_name
    }

@router.delete("/{class_id}")
async def delete_class(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Soft delete class"""
    service = ClassService(db)
    success = await service.soft_delete(class_id, tenant_id=(None if principal.is_super_admin else principal.tenant_id))

    if not success:
        raise HTTPException(status_code=404, detail="Class not found")
    
    return {"message": "Class deactivated successfully"}

# EXISTING UTILITY ENDPOINTS (continue with existing ones...)
@router.get("/tenant/{tenant_id}")
async def get_classes_by_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all classes for a specific school/tenant"""
    service = ClassService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    classes = await service.get_by_tenant(effective_tenant)
    
    return [
        {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "current_students": class_obj.current_students,
            "maximum_students": class_obj.maximum_students,
            "classroom": class_obj.classroom,
            "is_active": class_obj.is_active,
            "academic_year": class_obj.academic_year
        }
        for class_obj in classes
    ]

# NEW BULK OPERATION ENDPOINTS

@router.post("/bulk/import", response_model=dict)
async def bulk_import_classes(
    import_data: BulkClassImport,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Bulk import classes from CSV/JSON data"""
    service = ClassService(db)
    effective_tenant = import_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_import_classes(
        classes_data=import_data.classes,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Bulk import completed. {result['successful_imports']} classes imported successfully",
        **result
    }

@router.post("/bulk/update-capacity", response_model=dict)
async def bulk_update_capacity(
    capacity_data: BulkCapacityUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Bulk update class capacity"""
    service = ClassService(db)
    effective_tenant = capacity_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_update_capacity(
        capacity_updates=capacity_data.capacity_updates,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Capacity update completed. {result['updated_classes']} classes updated",
        **result
    }

@router.post("/bulk/update-status", response_model=dict)
async def bulk_update_status(
    status_data: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Bulk update class active status"""
    service = ClassService(db)
    effective_tenant = status_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_update_status(
        class_ids=status_data.class_ids,
        is_active=status_data.is_active,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Status update completed. {result['updated_classes']} classes updated to '{result['new_status']}'",
        **result
    }

@router.post("/bulk/assign-classrooms", response_model=dict)
async def bulk_assign_classrooms(
    assignment_data: BulkClassroomAssignment,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Bulk assign classrooms to classes"""
    service = ClassService(db)
    effective_tenant = assignment_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_assign_classrooms(
        classroom_assignments=assignment_data.classroom_assignments,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Classroom assignment completed. {result['updated_classes']} classes updated",
        **result
    }

@router.post("/bulk/academic-year-rollover", response_model=dict)
async def academic_year_rollover(
    rollover_data: AcademicYearRollover,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Rollover all classes to new academic year"""
    service = ClassService(db)
    effective_tenant = rollover_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_academic_year_rollover(
        current_year=rollover_data.current_year,
        new_year=rollover_data.new_year,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Academic year rollover completed. {result['rolled_over_classes']} classes rolled over from {result['previous_academic_year']} to {result['new_academic_year']}",
        **result
    }

@router.post("/bulk/delete", response_model=dict)
async def bulk_delete_classes(
    delete_data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Bulk soft delete classes"""
    service = ClassService(db)
    effective_tenant = delete_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_soft_delete(
        class_ids=delete_data.class_ids,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Bulk delete completed. {result['deleted_classes']} classes deactivated",
        **result
    }

@router.get("/statistics/{tenant_id}", response_model=dict)
async def get_comprehensive_statistics(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get comprehensive class statistics for a school"""
    service = ClassService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    stats = await service.get_comprehensive_class_statistics(effective_tenant)
    
    return {
        "message": "Class statistics retrieved successfully",
        **stats
    }

# Continue with existing endpoints...
@router.get("/grade/{grade_level}")
async def get_classes_by_grade(
    grade_level: int,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get classes by grade level"""
    service = ClassService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    classes = await service.get_by_grade_level(grade_level, effective_tenant)
    
    return [
        {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "section": class_obj.section,
            "current_students": class_obj.current_students,
            "maximum_students": class_obj.maximum_students,
            "classroom": class_obj.classroom,
            "academic_year": class_obj.academic_year,
            "is_active": class_obj.is_active
        }
        for class_obj in classes
    ]

@router.get("/availability/open")
async def get_classes_with_availability(
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get classes that have available spots for new students"""
    service = ClassService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    classes = await service.get_classes_with_availability(effective_tenant)
    
    return [
        {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "available_spots": class_obj.maximum_students - class_obj.current_students,
            "maximum_students": class_obj.maximum_students,
            "current_students": class_obj.current_students,
            "classroom": class_obj.classroom
        }
        for class_obj in classes
    ]

@router.get("/{class_id}/statistics")
async def get_class_statistics(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get detailed statistics for a specific class"""
    service = ClassService(db)
    # Tenant-scope the lookup before exposing statistics
    class_obj = await service.get(class_id, tenant_id=(None if principal.is_super_admin else principal.tenant_id))
    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")
    stats = await service.get_class_statistics(class_id)

    if not stats:
        raise HTTPException(status_code=404, detail="Class not found")
    
    return stats

@router.patch("/{class_id}/student-count")
async def update_student_count(
    class_id: UUID,
    student_count_data: StudentCountUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Update the current student count for a class"""
    service = ClassService(db)

    try:
        # Tenant-scope the lookup before mutating
        scoped = await service.get(class_id, tenant_id=(None if principal.is_super_admin else principal.tenant_id))
        if not scoped:
            raise HTTPException(status_code=404, detail="Class not found")
        class_obj = await service.update_student_count(class_id, student_count_data.current_students)
        if not class_obj:
            raise HTTPException(status_code=404, detail="Class not found")
        
        return {
            "id": str(class_obj.id),
            "message": "Student count updated successfully",
            "class_name": class_obj.class_name,
            "current_students": class_obj.current_students,
            "maximum_students": class_obj.maximum_students,
            "available_spots": class_obj.maximum_students - class_obj.current_students
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{class_id}/students", response_model=dict)
async def get_class_students(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all students enrolled in a specific class"""

    # Verify class exists
    class_stmt = select(ClassModel).where(ClassModel.id == class_id, ClassModel.is_deleted == False)
    if not principal.is_super_admin:
        class_stmt = class_stmt.where(ClassModel.tenant_id == principal.tenant_id)
    class_result = await db.execute(class_stmt)
    class_obj = class_result.scalar_one_or_none()

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get members enrolled in this class
    members_stmt = (
        select(Member, Enrollment)
        .join(Enrollment, Member.id == Enrollment.member_id)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active"
        )
        .order_by(Member.first_name, Member.last_name)
    )

    result = await db.execute(members_stmt)
    member_enrollments = result.all()

    students_data = [
        {
            "member_id": str(member.id),
            "member_name": f"{member.first_name or ''} {member.last_name or ''}".strip(),
            "member_hrid": member.staff_id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "status": enrollment.status,
            "email": member.email,
            "phone": member.phone,
            "enrollment_date": enrollment.enrollment_date.isoformat() if enrollment.enrollment_date else None,
            "academic_year": enrollment.academic_year
        }
        for member, enrollment in member_enrollments
    ]
    
    return {
        "class_info": {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "academic_year": class_obj.academic_year,
            "classroom": class_obj.classroom
        },
        "students": students_data,
        "total_students": len(students_data),
        "class_capacity": class_obj.maximum_students,
        "available_spots": class_obj.maximum_students - len(students_data)
    }

@router.post("/{class_id}/students", response_model=dict)
async def add_students_to_class(
    class_id: UUID,
    request: AddStudentsToClass,
    db: AsyncSession = Depends(get_db),
    # Adding a member to a class IS an enrolment write — allow either page to gate it.
    principal: Principal = Depends(require_authority_or_module('classes', 'enrollment'))  # writes: authority/super-admin/staff-with-page
):
    """Add multiple students to a class"""
    enrollment_service = EnrollmentService(db)

    try:
        # Tenant-scope the target class before enrolling students
        class_stmt = select(ClassModel).where(ClassModel.id == class_id, ClassModel.is_deleted == False)
        if not principal.is_super_admin:
            class_stmt = class_stmt.where(ClassModel.tenant_id == principal.tenant_id)
        class_result = await db.execute(class_stmt)
        if not class_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Class not found")
        result = await enrollment_service.bulk_enroll_students(
            class_id=class_id,
            member_ids=request.member_ids,
            academic_year=request.academic_year
        )

        return {
            "message": f"Successfully added {result['successful_enrollments']} members to class",
            "class_id": str(class_id),
            "successful_enrollments": result["successful_enrollments"],
            "failed_enrollments": result["failed_enrollments"],
            "successful_members": result["successful"],
            "failed_members": result["failed"],
            "class_capacity_after": result["class_capacity_after"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/academic-year/{academic_year}")
async def get_classes_by_academic_year(
    academic_year: str,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all classes for a specific academic year"""
    service = ClassService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    classes = await service.get_by_academic_year(academic_year, effective_tenant)
    
    return [
        {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "current_students": class_obj.current_students,
            "maximum_students": class_obj.maximum_students,
            "classroom": class_obj.classroom,
            "is_active": class_obj.is_active
        }
        for class_obj in classes
    ]

@router.post("/{class_id}/teachers", response_model=dict)
async def assign_teachers_to_class(
    class_id: UUID,
    request: AssignTeachersToClass,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('classes'))  # writes: authority/super-admin only
):
    """Assign teachers to a class"""
    try:
        # Get class (tenant-scoped)
        class_stmt = select(ClassModel).where(ClassModel.id == class_id, ClassModel.is_deleted == False)
        if not principal.is_super_admin:
            class_stmt = class_stmt.where(ClassModel.tenant_id == principal.tenant_id)
        class_result = await db.execute(class_stmt)
        class_obj = class_result.scalar_one_or_none()

        if not class_obj:
            raise HTTPException(status_code=404, detail="Class not found")

        # Get current assignments (make a copy to avoid reference issues)
        current_assignments = list(class_obj.assigned_teachers) if class_obj.assigned_teachers else []

        # Add new member (teacher) assignments
        for member_id in request.member_ids:
            # Verify member exists within the same tenant as the class
            member_stmt = select(Member).where(
                Member.id == member_id,
                Member.tenant_id == class_obj.tenant_id
            )
            member_result = await db.execute(member_stmt)
            member = member_result.scalar_one_or_none()

            if member:
                # Check if this member-subject combination already exists
                existing = next((a for a in current_assignments if a.get("member_id") == str(member_id) and a.get("subject_name") == request.subject_name), None)
                if not existing:
                    # Add new member-subject assignment
                    current_assignments.append({
                        "member_id": str(member_id),
                        "member_name": f"{member.first_name or ''} {member.last_name or ''}".strip(),
                        "subject_name": request.subject_name
                    })
        
        # Update class
        class_obj.assigned_teachers = current_assignments
        await db.commit()
        await db.refresh(class_obj)
        
        return {
            "message": f"Successfully assigned members to class",
            "class_id": str(class_id),
            "assigned_teachers": current_assignments
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{class_id}/teachers", response_model=dict)
async def get_class_teachers(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all teachers assigned to a specific class"""
    # Get class (tenant-scoped)
    class_stmt = select(ClassModel).where(ClassModel.id == class_id, ClassModel.is_deleted == False)
    if not principal.is_super_admin:
        class_stmt = class_stmt.where(ClassModel.tenant_id == principal.tenant_id)
    class_result = await db.execute(class_stmt)
    class_obj = class_result.scalar_one_or_none()

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    assigned_teachers = class_obj.assigned_teachers or []
    
    return {
        "class_info": {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "academic_year": class_obj.academic_year,
            "classroom": class_obj.classroom
        },
        "teachers": assigned_teachers,
        "total_teachers": len(assigned_teachers)
    }

@router.get("/teachers/available", response_model=dict)
async def get_available_teachers(
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all available members for assignment as teachers"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    # Get active members for the tenant
    members_stmt = select(Member).where(
        Member.tenant_id == effective_tenant,
        Member.status == "active"
    ).order_by(Member.first_name, Member.last_name)

    result = await db.execute(members_stmt)
    members = result.scalars().all()

    teachers_data = [
        {
            "member_id": str(member.id),
            "member_hrid": member.staff_id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "member_name": f"{member.first_name or ''} {member.last_name or ''}".strip(),
            "email": member.email,
            "phone": member.phone,
            "position": member.position,
            "experience_years": member.experience_years
        }
        for member in members
    ]
    
    return {
        "teachers": teachers_data,
        "total_teachers": len(teachers_data),
        "tenant_id": str(effective_tenant) if effective_tenant else None
    }

@router.get("/students/available-for-class/{class_id}", response_model=dict)
async def get_available_students_for_class(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get students available for enrollment in a specific class"""

    # Get class details (tenant-scoped)
    class_stmt = select(ClassModel).where(ClassModel.id == class_id, ClassModel.is_deleted == False)
    if not principal.is_super_admin:
        class_stmt = class_stmt.where(ClassModel.tenant_id == principal.tenant_id)
    class_result = await db.execute(class_stmt)
    class_obj = class_result.scalar_one_or_none()

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get members not already enrolled in any active class for current academic year
    members_stmt = (
        select(Member)
        .outerjoin(
            Enrollment,
            (Member.id == Enrollment.member_id) &
            (Enrollment.academic_year == class_obj.academic_year) &
            (Enrollment.status == "active") &
            (Enrollment.is_deleted == False)
        )
        .where(
            Member.tenant_id == class_obj.tenant_id,
            Member.status == "active",
            Enrollment.id.is_(None)  # Not enrolled in any active class
        )
        .order_by(Member.first_name, Member.last_name)
    )

    result = await db.execute(members_stmt)
    members = result.scalars().all()

    students_data = [
        {
            "member_id": str(member.id),
            "member_hrid": member.staff_id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "member_name": f"{member.first_name or ''} {member.last_name or ''}".strip(),
            "email": member.email,
            "phone": member.phone,
            "position": member.position
        }
        for member in members
    ]
    
    return {
        "class_info": {
            "id": str(class_obj.id),
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "academic_year": class_obj.academic_year,
            "available_spots": class_obj.maximum_students - class_obj.current_students
        },
        "available_students": students_data,
        "total_available": len(students_data)
    }
