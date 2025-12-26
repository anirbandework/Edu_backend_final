# app/routers/school_authority_management/exam_management.py
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from ...core.database import get_db
from ...services.exam_service import ExamService
from ...schemas.exam_schemas import (
    ExamCreate, ExamUpdate, ExamResponse, StudentMarkCreate, 
    StudentMarkUpdate, StudentMarkResponse, BulkMarkingRequest,
    BulkMarkingResponse, StudentExamHistory, ExamAnalytics
)

router = APIRouter(prefix="/exam-management", tags=["Exam Management"])

@router.post("/exams", response_model=ExamResponse)
async def create_exam(
    exam_data: ExamCreate,
    tenant_id: UUID = Query(...),
    created_by: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Create new exam with flexible configuration"""
    service = ExamService(db)
    try:
        exam = await service.create_exam(tenant_id, created_by, exam_data)
        return exam
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/exams", response_model=List[ExamResponse])
async def get_exams(
    tenant_id: UUID = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    exam_type: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Get exams with filtering and pagination"""
    service = ExamService(db)
    exams = await service.get_exams_by_tenant(tenant_id, skip, limit)
    return exams

@router.get("/exams/{exam_id}", response_model=ExamResponse)
async def get_exam(
    exam_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get exam by ID"""
    service = ExamService(db)
    exam = await service.get_exam_by_id(tenant_id, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam

@router.put("/exams/{exam_id}", response_model=ExamResponse)
async def update_exam(
    exam_id: UUID,
    exam_data: ExamUpdate,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Update exam"""
    service = ExamService(db)
    exam = await service.update_exam(tenant_id, exam_id, exam_data)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam

@router.post("/exams/{exam_id}/marks", response_model=StudentMarkResponse)
async def create_student_mark(
    exam_id: UUID,
    mark_data: StudentMarkCreate,
    tenant_id: UUID = Query(...),
    class_id: UUID = Query(...),
    marked_by: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Create or update student mark"""
    service = ExamService(db)
    try:
        mark = await service.create_student_mark(tenant_id, exam_id, class_id, marked_by, mark_data)
        return mark
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/exams/{exam_id}/bulk-marks", response_model=BulkMarkingResponse)
async def bulk_create_marks(
    exam_id: UUID,
    bulk_data: BulkMarkingRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Query(...),
    marked_by: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Bulk create/update student marks"""
    service = ExamService(db)
    try:
        # For large datasets, process in background
        if len(bulk_data.marks_data) > 100:
            background_tasks.add_task(
                service.bulk_create_marks, 
                tenant_id, exam_id, marked_by, bulk_data
            )
            return {
                "batch_id": "processing",
                "total_records": len(bulk_data.marks_data),
                "success_count": 0,
                "error_count": 0,
                "message": "Large dataset - processing in background"
            }
        else:
            result = await service.bulk_create_marks(tenant_id, exam_id, marked_by, bulk_data)
            return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/students/{student_id}/exam-history")
async def get_student_exam_history(
    student_id: UUID,
    tenant_id: UUID = Query(...),
    academic_year: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Get student's exam history"""
    service = ExamService(db)
    try:
        history = await service.get_student_exam_history(tenant_id, student_id)
        return {
            "student_id": str(student_id),
            "exams": history
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exams/{exam_id}/analytics", response_model=ExamAnalytics)
async def get_exam_analytics(
    exam_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get exam analytics and statistics"""
    service = ExamService(db)
    try:
        analytics = await service.get_exam_analytics(tenant_id, exam_id)
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
    tenant_id: UUID = Query(...),
    class_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """Get exam marks with filtering"""
    from sqlalchemy import text, and_
    
    # Use raw SQL for better performance
    base_query = """
        SELECT 
            sem.id,
            sem.student_id,
            s.first_name,
            s.last_name,
            s.roll_number,
            sem.marks_data,
            sem.total_marks,
            sem.obtained_marks,
            sem.percentage,
            sem.grade,
            sem.marking_status,
            sem.marked_at,
            sem.remarks
        FROM student_exam_marks sem
        JOIN students s ON sem.student_id = s.id
        WHERE sem.exam_id = :exam_id AND sem.tenant_id = :tenant_id
    """
    
    params = {"exam_id": str(exam_id), "tenant_id": str(tenant_id)}
    
    if class_id:
        base_query += " AND sem.class_id = :class_id"
        params["class_id"] = str(class_id)
    
    base_query += " ORDER BY s.roll_number, s.first_name LIMIT :limit OFFSET :skip"
    params.update({"limit": limit, "skip": skip})
    
    result = await db.execute(text(base_query), params)
    marks = result.fetchall()
    
    return [{
        "id": str(mark.id),
        "student_id": str(mark.student_id),
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
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Soft delete exam"""
    service = ExamService(db)
    exam = await service.get_exam_by_id(tenant_id, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    exam.is_deleted = True
    await db.commit()
    return {"message": "Exam deleted successfully"}

@router.post("/exams/{exam_id}/publish")
async def publish_exam_results(
    exam_id: UUID,
    tenant_id: UUID = Query(...),
    published_by: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Publish exam results"""
    service = ExamService(db)
    exam = await service.get_exam_by_id(tenant_id, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    exam.is_published = True
    exam.published_at = datetime.utcnow()
    exam.published_by = published_by
    exam.status = "results_published"
    
    await db.commit()
    return {"message": "Exam results published successfully"}