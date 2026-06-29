# app/routers/school_authority/enrollment.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime
from ...core.database import get_db
from ...enrollment_management.models.enrollment import Enrollment
from ...enrollment_management.services.enrollment_service import EnrollmentService
from ...staff_management.models.member import Member
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_authority, assert_same_tenant
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal


async def _member_lookup(db: AsyncSession, member_ids) -> dict:
    """Return {member_id(str): (member_name, member_hrid)} for the given ids."""
    ids = list({str(mid) for mid in member_ids if mid is not None})
    if not ids:
        return {}
    result = await db.execute(select(Member).where(Member.id.in_(ids)))
    out = {}
    for m in result.scalars().all():
        name = f"{m.first_name or ''} {m.last_name or ''}".strip()
        out[str(m.id)] = (name, m.staff_id)
    return out

# Existing Pydantic Models
class EnrollmentCreate(BaseModel):
    member_id: UUID
    class_id: UUID
    academic_year: str
    enrollment_date: datetime = datetime.utcnow()
    status: str = "active"

class EnrollmentUpdate(BaseModel):
    academic_year: Optional[str] = None
    enrollment_date: Optional[datetime] = None
    status: Optional[str] = None

class BulkEnrollmentCreate(BaseModel):
    class_id: UUID
    member_ids: List[UUID]
    academic_year: str

class StatusUpdate(BaseModel):
    status: str

# NEW BULK OPERATION MODELS
class BulkEnrollmentImport(BaseModel):
    enrollments: List[dict]  # [{"member_id": UUID, "class_id": UUID, "academic_year": str}]

class BulkStatusUpdate(BaseModel):
    enrollment_ids: List[UUID]
    new_status: str

class BulkTransferStudents(BaseModel):
    member_ids: List[UUID]
    from_class_id: UUID
    to_class_id: UUID
    academic_year: str

class AcademicYearRollover(BaseModel):
    current_year: str
    new_year: str
    tenant_id: UUID

class BulkDeleteRequest(BaseModel):
    enrollment_ids: List[UUID]

class BulkEnrollByGrade(BaseModel):
    grade_level: int
    target_class_ids: List[UUID]  # Classes to distribute students across
    academic_year: str
    tenant_id: UUID

class BulkWithdrawStudents(BaseModel):
    member_ids: List[UUID]
    academic_year: str
    withdrawal_reason: Optional[str] = "Withdrawn"

router = APIRouter(prefix="/api/v1/school_authority/enrollments", tags=["School Authority - Enrollment Management"])

# EXISTING ENDPOINTS (unchanged)
@router.get("/", response_model=dict)
async def get_enrollments(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    member_id: Optional[UUID] = Query(None),
    class_id: Optional[UUID] = Query(None),
    academic_year: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get paginated enrollments with filtering"""
    service = EnrollmentService(db)

    try:
        result = await service.get_enrollments_paginated(
            page=page,
            size=size,
            member_id=member_id,
            class_id=class_id,
            academic_year=academic_year,
            status=status
        )

        members = await _member_lookup(db, [e.member_id for e in result["items"]])
        formatted_enrollments = [
            {
                "id": str(enrollment.id),
                "member_id": str(enrollment.member_id),
                "class_id": str(enrollment.class_id),
                "academic_year": enrollment.academic_year,
                "enrollment_date": enrollment.enrollment_date.isoformat(),
                "status": enrollment.status,
                "member_name": members.get(str(enrollment.member_id), (None, None))[0],
                "member_hrid": members.get(str(enrollment.member_id), (None, None))[1],
                "created_at": enrollment.created_at.isoformat(),
                "updated_at": enrollment.updated_at.isoformat()
            }
            for enrollment in result["items"]
        ]

        return {
            "items": formatted_enrollments,
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
async def create_enrollment(
    enrollment_data: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Create new enrollment"""
    service = EnrollmentService(db)

    enrollment_dict = enrollment_data.model_dump()
    scope_tenant = None if principal.is_super_admin else principal.tenant_id
    enrollment = await service.create(enrollment_dict, scope_tenant=scope_tenant)

    members = await _member_lookup(db, [enrollment.member_id])
    member_name, member_hrid = members.get(str(enrollment.member_id), (None, None))
    return {
        "id": str(enrollment.id),
        "message": "Member enrolled successfully",
        "member_id": str(enrollment.member_id),
        "class_id": str(enrollment.class_id),
        "academic_year": enrollment.academic_year,
        "status": enrollment.status,
        "enrollment_date": enrollment.enrollment_date.isoformat(),
        "member_name": member_name,
        "member_hrid": member_hrid
    }

@router.post("/bulk", response_model=dict)
async def bulk_enroll_students(
    bulk_data: BulkEnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Bulk enroll multiple students in a class"""
    service = EnrollmentService(db)
    
    result = await service.bulk_enroll_students(
        class_id=bulk_data.class_id,
        member_ids=bulk_data.member_ids,
        academic_year=bulk_data.academic_year,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id),
    )
    
    return {
        "message": f"Bulk enrollment completed. {result['successful_enrollments']} successful, {result['failed_enrollments']} failed",
        **result
    }

# NEW ADVANCED BULK OPERATION ENDPOINTS

@router.post("/bulk/import", response_model=dict)
async def bulk_import_enrollments(
    import_data: BulkEnrollmentImport,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Bulk import enrollments from CSV/JSON data"""
    service = EnrollmentService(db)
    
    result = await service.bulk_import_enrollments(
        enrollments_data=import_data.enrollments,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id),
    )
    
    return {
        "message": f"Bulk import completed. {result['successful_enrollments']} enrollments imported successfully",
        **result
    }

@router.post("/bulk/update-status", response_model=dict)
async def bulk_update_enrollment_status(
    status_data: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Bulk update enrollment status"""
    service = EnrollmentService(db)
    
    result = await service.bulk_update_enrollment_status(
        enrollment_ids=status_data.enrollment_ids,
        new_status=status_data.new_status,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id),
    )
    
    return {
        "message": f"Status update completed. {result['updated_enrollments']} enrollments updated to '{result['new_status']}'",
        **result
    }

@router.post("/bulk/transfer", response_model=dict)
async def bulk_transfer_students(
    transfer_data: BulkTransferStudents,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Bulk transfer students between classes"""
    service = EnrollmentService(db)
    
    result = await service.bulk_transfer_students(
        member_ids=transfer_data.member_ids,
        from_class_id=transfer_data.from_class_id,
        to_class_id=transfer_data.to_class_id,
        academic_year=transfer_data.academic_year,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id),
    )
    
    return {
        "message": f"Transfer completed. {result['transferred_students']} students transferred from {result['from_class_id']} to {result['to_class_id']}",
        **result
    }

@router.post("/bulk/academic-year-rollover", response_model=dict)
async def academic_year_rollover(
    rollover_data: AcademicYearRollover,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Promote all students to next academic year"""
    service = EnrollmentService(db)

    # Never trust the client-supplied tenant_id for authorization.
    effective_tenant = rollover_data.tenant_id if principal.is_super_admin else principal.tenant_id
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="A tenant_id is required for academic year rollover")

    result = await service.academic_year_rollover(
        current_year=rollover_data.current_year,
        new_year=rollover_data.new_year,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Academic year rollover completed. {result['promoted_students']} students promoted from {result['previous_academic_year']} to {result['new_academic_year']}",
        **result
    }

@router.post("/bulk/enroll-by-grade", response_model=dict)
async def bulk_enroll_by_grade(
    grade_data: BulkEnrollByGrade,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Bulk enroll students by grade level across multiple classes"""
    service = EnrollmentService(db)

    # Never trust the client-supplied tenant_id for authorization.
    effective_tenant = grade_data.tenant_id if principal.is_super_admin else principal.tenant_id
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="A tenant_id is required for grade-based enrollment")

    result = await service.bulk_enroll_by_grade(
        grade_level=grade_data.grade_level,
        target_class_ids=grade_data.target_class_ids,
        academic_year=grade_data.academic_year,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Grade-based enrollment completed. {result['enrolled_students']} students from grade {grade_data.grade_level} enrolled across {len(grade_data.target_class_ids)} classes",
        **result
    }

@router.post("/bulk/withdraw", response_model=dict)
async def bulk_withdraw_students(
    withdraw_data: BulkWithdrawStudents,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Bulk withdraw students from all enrollments"""
    service = EnrollmentService(db)
    
    result = await service.bulk_withdraw_students(
        member_ids=withdraw_data.member_ids,
        academic_year=withdraw_data.academic_year,
        withdrawal_reason=withdraw_data.withdrawal_reason,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id),
    )
    
    return {
        "message": f"Withdrawal completed. {result['withdrawn_students']} students withdrawn from all classes",
        **result
    }

@router.post("/bulk/auto-assign", response_model=dict)
async def bulk_auto_assign_enrollments(
    academic_year: str,
    tenant_id: Optional[UUID] = Query(None),
    grade_level: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Auto-assign unenrolled students to available classes"""
    service = EnrollmentService(db)

    # Never trust the client-supplied tenant_id for authorization.
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="A tenant_id is required for auto-assignment")

    result = await service.bulk_auto_assign_enrollments(
        tenant_id=effective_tenant,
        academic_year=academic_year,
        grade_level=grade_level
    )
    
    return {
        "message": f"Auto-assignment completed. {result['assigned_students']} students assigned to classes",
        **result
    }

@router.post("/bulk/delete", response_model=dict, dependencies=[Depends(require_super_admin)])
async def bulk_delete_enrollments(
    delete_data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Bulk soft delete enrollments"""
    service = EnrollmentService(db)
    
    result = await service.bulk_soft_delete_enrollments(
        enrollment_ids=delete_data.enrollment_ids
    )
    
    return {
        "message": f"Bulk delete completed. {result['deleted_enrollments']} enrollments removed",
        **result
    }

@router.get("/statistics/comprehensive")
async def get_comprehensive_enrollment_statistics(
    academic_year: Optional[str] = Query(None),
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get comprehensive enrollment statistics"""
    service = EnrollmentService(db)

    # Never trust the client-supplied tenant_id for authorization.
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="A tenant_id is required for enrollment statistics")

    stats = await service.get_comprehensive_enrollment_statistics(
        tenant_id=effective_tenant,
        academic_year=academic_year
    )
    
    return {
        "message": "Enrollment statistics retrieved successfully",
        **stats
    }

# EXISTING UTILITY ENDPOINTS (unchanged)
@router.get("/{enrollment_id}", response_model=dict)
async def get_enrollment(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get specific enrollment details"""
    service = EnrollmentService(db)
    scope_tenant = None if principal.is_super_admin else principal.tenant_id
    enrollment = await service.get(enrollment_id, tenant_id=scope_tenant)

    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    members = await _member_lookup(db, [enrollment.member_id])
    member_name, member_hrid = members.get(str(enrollment.member_id), (None, None))
    return {
        "id": str(enrollment.id),
        "member_id": str(enrollment.member_id),
        "class_id": str(enrollment.class_id),
        "academic_year": enrollment.academic_year,
        "enrollment_date": enrollment.enrollment_date.isoformat(),
        "status": enrollment.status,
        "member_name": member_name,
        "member_hrid": member_hrid,
        "created_at": enrollment.created_at.isoformat(),
        "updated_at": enrollment.updated_at.isoformat()
    }

@router.put("/{enrollment_id}", response_model=dict)
async def update_enrollment(
    enrollment_id: UUID,
    enrollment_data: EnrollmentUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Update enrollment information"""
    service = EnrollmentService(db)
    scope_tenant = None if principal.is_super_admin else principal.tenant_id

    update_dict = enrollment_data.model_dump(exclude_unset=True)
    enrollment = await service.update(enrollment_id, update_dict, tenant_id=scope_tenant)
    
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    return {
        "id": str(enrollment.id),
        "message": "Enrollment updated successfully"
    }

@router.patch("/{enrollment_id}/status")
async def update_enrollment_status(
    enrollment_id: UUID,
    status_data: StatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Update enrollment status"""
    service = EnrollmentService(db)
    scope_tenant = None if principal.is_super_admin else principal.tenant_id

    enrollment = await service.update_enrollment_status(enrollment_id, status_data.status, tenant_id=scope_tenant)
    
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    return {
        "id": str(enrollment.id),
        "message": f"Enrollment status updated to {status_data.status}",
        "status": enrollment.status
    }

@router.delete("/{enrollment_id}")
async def delete_enrollment(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('enrollment'))  # writes: authority/super-admin only
):
    """Soft delete enrollment"""
    service = EnrollmentService(db)
    scope_tenant = None if principal.is_super_admin else principal.tenant_id
    success = await service.soft_delete(enrollment_id, tenant_id=scope_tenant)
    
    if not success:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    return {"message": "Enrollment removed successfully"}

@router.get("/member/{member_id}")
async def get_member_enrollments(
    member_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all enrollments for a specific member"""
    service = EnrollmentService(db)
    enrollments = await service.get_by_member(member_id)

    return [
        {
            "id": str(enrollment.id),
            "class_id": str(enrollment.class_id),
            "academic_year": enrollment.academic_year,
            "enrollment_date": enrollment.enrollment_date.isoformat(),
            "status": enrollment.status
        }
        for enrollment in enrollments
    ]

@router.get("/class/{class_id}")
async def get_class_enrollments(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get the roster (members) for a specific class"""
    service = EnrollmentService(db)
    enrollments = await service.get_by_class(class_id)

    members = await _member_lookup(db, [e.member_id for e in enrollments])
    return [
        {
            "member_id": str(enrollment.member_id),
            "name": members.get(str(enrollment.member_id), (None, None))[0],
            "hrid": members.get(str(enrollment.member_id), (None, None))[1],
            "status": enrollment.status
        }
        for enrollment in enrollments
    ]

@router.get("/academic-year/{academic_year}")
async def get_enrollments_by_academic_year(
    academic_year: str,
    member_id: Optional[UUID] = Query(None),
    class_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get enrollments by academic year"""
    service = EnrollmentService(db)
    enrollments = await service.get_by_academic_year(academic_year, member_id, class_id)

    members = await _member_lookup(db, [e.member_id for e in enrollments])
    return [
        {
            "id": str(enrollment.id),
            "member_id": str(enrollment.member_id),
            "class_id": str(enrollment.class_id),
            "enrollment_date": enrollment.enrollment_date.isoformat(),
            "status": enrollment.status,
            "member_name": members.get(str(enrollment.member_id), (None, None))[0],
            "member_hrid": members.get(str(enrollment.member_id), (None, None))[1]
        }
        for enrollment in enrollments
    ]
