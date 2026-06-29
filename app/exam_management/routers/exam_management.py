# app/routers/school_authority_management/exam_management.py
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_staff, assert_same_tenant
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal
from ...exam_management.services.exam_service import ExamService
from ...exam_management.schemas.exam_schemas import (
    ExamCreate, ExamUpdate, ExamResponse, StudentMarkCreate, 
    StudentMarkUpdate, StudentMarkResponse, BulkMarkingRequest,
    BulkMarkingResponse, StudentExamHistory, ExamAnalytics
)

router = APIRouter(prefix="/exam-management", tags=["Exam Management"])

@router.post("/exams", response_model=ExamResponse)
async def create_exam(
    exam_data: ExamCreate,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('exams'))  # staff (teacher/authority/super-admin) only
):
    """Create new exam with flexible configuration"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    # The acting/creating user is always the authenticated principal.
    created_by = principal.user_id
    service = ExamService(db)
    try:
        exam = await service.create_exam(effective_tenant, created_by, exam_data)
        return exam
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/exams", response_model=List[ExamResponse])
async def get_exams(
    tenant_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    exam_type: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get exams with filtering and pagination"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = ExamService(db)
    exams = await service.get_exams_by_tenant(effective_tenant, skip, limit)
    return exams

@router.get("/exams/{exam_id}", response_model=ExamResponse)
async def get_exam(
    exam_id: UUID,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get exam by ID"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = ExamService(db)
    exam = await service.get_exam_by_id(effective_tenant, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam

@router.put("/exams/{exam_id}", response_model=ExamResponse)
async def update_exam(
    exam_id: UUID,
    exam_data: ExamUpdate,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('exams'))  # staff (teacher/authority/super-admin) only
):
    """Update exam"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = ExamService(db)
    exam = await service.update_exam(effective_tenant, exam_id, exam_data)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam

@router.post("/exams/{exam_id}/marks", response_model=StudentMarkResponse)
async def create_student_mark(
    exam_id: UUID,
    mark_data: StudentMarkCreate,
    class_id: UUID = Query(...),
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('exams'))  # staff (teacher/authority/super-admin) only
):
    """Create or update student mark"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    # The user recording the mark is always the authenticated principal.
    marked_by = principal.user_id
    service = ExamService(db)
    try:
        mark = await service.create_student_mark(effective_tenant, exam_id, class_id, marked_by, mark_data)
        return mark
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/exams/{exam_id}/bulk-marks", response_model=BulkMarkingResponse)
async def bulk_create_marks(
    exam_id: UUID,
    bulk_data: BulkMarkingRequest,
    background_tasks: BackgroundTasks,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('exams'))  # staff (teacher/authority/super-admin) only
):
    """Bulk create/update student marks"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    # The user recording the marks is always the authenticated principal.
    marked_by = principal.user_id
    service = ExamService(db)
    try:
        # For large datasets, process in background
        if len(bulk_data.marks_data) > 100:
            background_tasks.add_task(
                service.bulk_create_marks,
                effective_tenant, exam_id, marked_by, bulk_data
            )
            return {
                "batch_id": "processing",
                "total_records": len(bulk_data.marks_data),
                "success_count": 0,
                "error_count": 0,
                "message": "Large dataset - processing in background"
            }
        else:
            result = await service.bulk_create_marks(effective_tenant, exam_id, marked_by, bulk_data)
            return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/students/{student_id}/exam-history")
async def get_student_exam_history(
    student_id: UUID,
    tenant_id: Optional[UUID] = Query(None),
    academic_year: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get student's exam history"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = ExamService(db)
    try:
        history = await service.get_student_exam_history(effective_tenant, student_id)
        return {
            "student_id": str(student_id),
            "exams": history
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/students/{student_id}/report-card")
async def get_student_report_card(
    student_id: UUID,
    tenant_id: Optional[UUID] = Query(None),
    academic_year: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Report card aggregated from the student's actual exam marks, grouped by
    subject (overall %, per-subject average, grade, pass/fail)."""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = ExamService(db)
    try:
        return await service.get_student_report_card(
            effective_tenant, student_id, academic_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exams/{exam_id}/analytics", response_model=ExamAnalytics)
async def get_exam_analytics(
    exam_id: UUID,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get exam analytics and statistics"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = ExamService(db)
    try:
        analytics = await service.get_exam_analytics(effective_tenant, exam_id)
        return {
            "exam_id": str(exam_id),
            "exam_name": "Exam Analytics",  # You might want to fetch this
            **analytics
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/exams/{exam_id}/marks")
async def get_exam_marks(
    exam_id: UUID,
    tenant_id: Optional[UUID] = Query(None),
    class_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get exam marks with filtering"""
    from sqlalchemy import text, and_

    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    # Use raw SQL for better performance
    base_query = """
        SELECT 
            sem.id,
            sem.member_id,
            s.first_name,
            s.last_name,
            (s.profile ->> 'roll_number') AS roll_number,
            sem.marks_data,
            sem.total_marks,
            sem.obtained_marks,
            sem.percentage,
            sem.grade,
            sem.marking_status,
            sem.marked_at,
            sem.remarks
        FROM student_exam_marks sem
        JOIN members s ON sem.member_id = s.id
        WHERE sem.exam_id = :exam_id
    """

    params = {"exam_id": str(exam_id)}

    # Non-super-admins are always scoped to their own tenant. A super-admin may
    # optionally scope to a specific tenant; without one they see across tenants.
    if effective_tenant is not None:
        base_query += " AND sem.tenant_id = :tenant_id"
        params["tenant_id"] = str(effective_tenant)
    elif not principal.is_super_admin:
        # Defensive: a non-super-admin with no tenant cannot see any marks.
        raise HTTPException(status_code=403, detail="No tenant context for this principal")

    if class_id:
        base_query += " AND sem.class_id = :class_id"
        params["class_id"] = str(class_id)
    
    base_query += " ORDER BY (s.profile ->> 'roll_number'), s.first_name LIMIT :limit OFFSET :skip"
    params.update({"limit": limit, "skip": skip})
    
    result = await db.execute(text(base_query), params)
    marks = result.fetchall()
    
    return [{
        "id": str(mark.id),
        "student_id": str(mark.member_id),  # API key kept; value is a members.id
        "first_name": mark.first_name,
        "last_name": mark.last_name,
        "roll_number": mark.roll_number,
        "marks_data": mark.marks_data,
        "total_marks": mark.total_marks,
        "obtained_marks": mark.obtained_marks,
        "percentage": mark.percentage,
        "grade": mark.grade,
        "marking_status": mark.marking_status,
        "marked_at": mark.marked_at.isoformat() if mark.marked_at else None,
        "remarks": mark.remarks
    } for mark in marks]

@router.delete("/exams/{exam_id}")
async def delete_exam(
    exam_id: UUID,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('exams'))
):
    """Soft delete exam"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    service = ExamService(db)
    exam = await service.get_exam_by_id(effective_tenant, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    # Defense in depth: ensure the fetched exam belongs to a tenant the caller may act on.
    assert_same_tenant(principal, getattr(exam, "tenant_id", None))

    exam.is_deleted = True
    await db.commit()
    return {"message": "Exam deleted successfully"}

@router.post("/exams/{exam_id}/publish")
async def publish_exam_results(
    exam_id: UUID,
    tenant_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('exams'))
):
    """Publish exam results"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    # The publishing user is always the authenticated principal.
    published_by = principal.user_id
    service = ExamService(db)
    exam = await service.get_exam_by_id(effective_tenant, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    # Defense in depth: ensure the fetched exam belongs to a tenant the caller may act on.
    assert_same_tenant(principal, getattr(exam, "tenant_id", None))

    exam.is_published = True
    exam.published_at = datetime.utcnow()
    exam.published_by = published_by
    exam.status = "results_published"
    
    await db.commit()
    return {"message": "Exam results published successfully"}