# app/services/exam_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, and_, or_, func
from typing import List, Dict, Any, Optional
from uuid import UUID
import uuid
from datetime import datetime

from ..models.tenant_specific.exam_management import (
    Exam, ExamClass, StudentExamMark, ExamTemplate, BulkMarkingBatch
)
from ..models.tenant_specific.student import Student
from ..models.tenant_specific.class_model import ClassModel
from ..schemas.exam_schemas import (
    ExamCreate, ExamUpdate, StudentMarkCreate, StudentMarkUpdate, BulkMarkingRequest
)

class ExamService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_exam(self, tenant_id: UUID, created_by: UUID, exam_data: ExamCreate) -> Exam:
        """Create new exam with flexible configuration"""
        exam = Exam(
            tenant_id=tenant_id,
            created_by=created_by,
            exam_name=exam_data.exam_name,
            exam_code=exam_data.exam_code,
            exam_type=exam_data.exam_type,
            description=exam_data.description,
            academic_year=exam_data.academic_year,
            term=exam_data.term,
            subject=exam_data.subject,
            grade_levels=exam_data.grade_levels,
            exam_date=exam_data.exam_date,
            start_time=exam_data.start_time,
            end_time=exam_data.end_time,
            duration_minutes=exam_data.duration_minutes,
            exam_config=exam_data.exam_config or {},
            marking_scheme=exam_data.marking_scheme or {},
            grading_criteria=exam_data.grading_criteria or {}
        )
        
        self.db.add(exam)
        await self.db.flush()
        
        # Add exam classes
        for class_id in exam_data.class_ids:
            exam_class = ExamClass(
                tenant_id=tenant_id,
                exam_id=exam.id,
                class_id=UUID(class_id)
            )
            self.db.add(exam_class)
        
        await self.db.commit()
        await self.db.refresh(exam)
        return exam

    async def get_exams_by_tenant(self, tenant_id: UUID, skip: int = 0, limit: int = 100) -> List[Exam]:
        """Get exams with optimized query for large datasets"""
        from sqlalchemy import select
        
        stmt = select(Exam).filter(
            and_(
                Exam.tenant_id == tenant_id,
                Exam.is_deleted == False
            )
        ).order_by(Exam.created_at.desc()).offset(skip).limit(limit)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_exam_by_id(self, tenant_id: UUID, exam_id: UUID) -> Optional[Exam]:
        """Get exam by ID with tenant validation"""
        from sqlalchemy import select
        
        stmt = select(Exam).filter(
            and_(
                Exam.id == exam_id,
                Exam.tenant_id == tenant_id,
                Exam.is_deleted == False
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_exam(self, tenant_id: UUID, exam_id: UUID, exam_data: ExamUpdate) -> Optional[Exam]:
        """Update exam with validation"""
        exam = await self.get_exam_by_id(tenant_id, exam_id)
        if not exam:
            return None
        
        update_data = exam_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(exam, field, value)
        
        await self.db.commit()
        return exam

    async def create_student_mark(self, tenant_id: UUID, exam_id: UUID, class_id: UUID, 
                          marked_by: UUID, mark_data: StudentMarkCreate) -> StudentExamMark:
        """Create or update student mark"""
        from sqlalchemy import select
        
        # Check if mark already exists
        stmt = select(StudentExamMark).filter(
            and_(
                StudentExamMark.exam_id == exam_id,
                StudentExamMark.student_id == UUID(mark_data.student_id),
                StudentExamMark.tenant_id == tenant_id
            )
        )
        result = await self.db.execute(stmt)
        existing_mark = result.scalar_one_or_none()
        
        if existing_mark:
            # Update existing mark
            for field, value in mark_data.dict(exclude_unset=True).items():
                if field != 'student_id':
                    setattr(existing_mark, field, value)
            existing_mark.marked_by = marked_by
            existing_mark.marked_at = datetime.utcnow()
            await self.db.commit()
            return existing_mark
        
        # Create new mark
        student_mark = StudentExamMark(
            tenant_id=tenant_id,
            exam_id=exam_id,
            student_id=UUID(mark_data.student_id),
            class_id=class_id,
            marks_data=mark_data.marks_data,
            total_marks=mark_data.total_marks,
            obtained_marks=mark_data.obtained_marks,
            percentage=mark_data.percentage,
            grade=mark_data.grade,
            remarks=mark_data.remarks,
            attendance_status=mark_data.attendance_status,
            marked_by=marked_by,
            marked_at=datetime.utcnow()
        )
        
        self.db.add(student_mark)
        await self.db.commit()
        return student_mark

    async def bulk_create_marks(self, tenant_id: UUID, exam_id: UUID, marked_by: UUID, 
                         bulk_data: BulkMarkingRequest) -> Dict[str, Any]:
        """Bulk create/update student marks with optimized performance"""
        batch = BulkMarkingBatch(
            tenant_id=tenant_id,
            exam_id=UUID(bulk_data.exam_id),
            uploaded_by=marked_by,
            batch_name=bulk_data.batch_name or f"Bulk_Upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            total_records=len(bulk_data.marks_data),
            started_at=datetime.utcnow()
        )
        
        self.db.add(batch)
        await self.db.flush()
        
        success_count = 0
        error_count = 0
        errors = []
        
        try:
            # Use raw SQL for better performance with large datasets
            for i, mark_data in enumerate(bulk_data.marks_data):
                try:
                    # Get class_id for student
                    class_query = text("""
                        SELECT c.id FROM classes c
                        JOIN enrollments e ON c.id = e.class_id
                        WHERE e.student_id = :student_id AND c.tenant_id = :tenant_id
                        AND e.status = 'active'
                        LIMIT 1
                    """)
                    
                    class_result = await self.db.execute(class_query, {
                        "student_id": mark_data.student_id,
                        "tenant_id": str(tenant_id)
                    })
                    class_row = class_result.fetchone()
                    
                    if not class_row:
                        errors.append({
                            "row": i + 1,
                            "student_id": mark_data.student_id,
                            "error": "Student not found or not enrolled"
                        })
                        error_count += 1
                        continue
                    
                    class_id = class_row[0]
                    
                    # Upsert student mark using raw SQL for performance
                    upsert_query = text("""
                        INSERT INTO student_exam_marks (
                            id, tenant_id, exam_id, student_id, class_id, marks_data,
                            total_marks, obtained_marks, percentage, grade, remarks,
                            attendance_status, marked_by, marked_at, created_at, updated_at
                        ) VALUES (
                            :id, :tenant_id, :exam_id, :student_id, :class_id, :marks_data,
                            :total_marks, :obtained_marks, :percentage, :grade, :remarks,
                            :attendance_status, :marked_by, :marked_at, :created_at, :updated_at
                        )
                        ON CONFLICT (exam_id, student_id)
                        DO UPDATE SET
                            marks_data = EXCLUDED.marks_data,
                            total_marks = EXCLUDED.total_marks,
                            obtained_marks = EXCLUDED.obtained_marks,
                            percentage = EXCLUDED.percentage,
                            grade = EXCLUDED.grade,
                            remarks = EXCLUDED.remarks,
                            attendance_status = EXCLUDED.attendance_status,
                            marked_by = EXCLUDED.marked_by,
                            marked_at = EXCLUDED.marked_at,
                            updated_at = EXCLUDED.updated_at
                    """)
                    
                    import json
                    now = datetime.utcnow()
                    await self.db.execute(upsert_query, {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "exam_id": str(exam_id),
                        "student_id": mark_data.student_id,
                        "class_id": str(class_id),
                        "marks_data": json.dumps(mark_data.marks_data),
                        "total_marks": mark_data.total_marks,
                        "obtained_marks": mark_data.obtained_marks,
                        "percentage": mark_data.percentage,
                        "grade": mark_data.grade,
                        "remarks": mark_data.remarks,
                        "attendance_status": mark_data.attendance_status,
                        "marked_by": str(marked_by),
                        "marked_at": now,
                        "created_at": now,
                        "updated_at": now
                    })
                    
                    success_count += 1
                    
                except Exception as e:
                    errors.append({
                        "row": i + 1,
                        "student_id": mark_data.student_id,
                        "error": str(e)
                    })
                    error_count += 1
            
            # Update batch status
            batch.success_count = success_count
            batch.error_count = error_count
            batch.processed_records = success_count + error_count
            batch.status = "completed"
            batch.completed_at = datetime.utcnow()
            batch.error_details = errors if errors else None
            
            await self.db.commit()
            
            return {
                "batch_id": str(batch.id),
                "total_records": len(bulk_data.marks_data),
                "success_count": success_count,
                "error_count": error_count,
                "errors": errors[:10] if errors else None  # Limit errors in response
            }
            
        except Exception as e:
            batch.status = "failed"
            batch.error_details = [{"error": str(e)}]
            await self.db.commit()
            raise

    async def get_student_exam_history(self, tenant_id: UUID, student_id: UUID) -> List[Dict[str, Any]]:
        """Get student's exam history with optimized query"""
        from sqlalchemy import select
        
        # Use async select query
        stmt = select(
            Exam.id.label('exam_id'),
            Exam.exam_name,
            Exam.exam_type,
            Exam.exam_date,
            Exam.subject,
            StudentExamMark.marks_data,
            StudentExamMark.total_marks,
            StudentExamMark.obtained_marks,
            StudentExamMark.percentage,
            StudentExamMark.grade,
            StudentExamMark.marking_status,
            StudentExamMark.marked_at
        ).select_from(
            Exam
        ).outerjoin(
            StudentExamMark, 
            and_(
                Exam.id == StudentExamMark.exam_id,
                StudentExamMark.student_id == student_id
            )
        ).filter(
            and_(
                Exam.tenant_id == tenant_id,
                Exam.is_deleted == False
            )
        ).order_by(Exam.exam_date.desc(), Exam.created_at.desc())
        
        result = await self.db.execute(stmt)
        rows = result.fetchall()
        
        return [{
            'exam_id': str(r.exam_id),
            'exam_name': r.exam_name,
            'exam_type': r.exam_type,
            'exam_date': r.exam_date.isoformat() if r.exam_date else None,
            'subject': r.subject,
            'marks_data': r.marks_data,
            'total_marks': r.total_marks,
            'obtained_marks': r.obtained_marks,
            'percentage': r.percentage,
            'grade': r.grade,
            'marking_status': r.marking_status,
            'marked_at': r.marked_at.isoformat() if r.marked_at else None
        } for r in rows]

    async def get_exam_analytics(self, tenant_id: UUID, exam_id: UUID) -> Dict[str, Any]:
        """Get exam analytics using ORM for better compatibility"""
        from sqlalchemy import select
        
        # Get basic statistics
        stmt = select(StudentExamMark).filter(
            and_(
                StudentExamMark.exam_id == exam_id,
                StudentExamMark.tenant_id == tenant_id
            )
        )
        result = await self.db.execute(stmt)
        marks = result.scalars().all()
        
        total_students = len(marks)
        appeared_students = len([m for m in marks if m.marking_status != 'pending'])
        
        obtained_marks = [m.obtained_marks for m in marks if m.obtained_marks is not None]
        avg_marks = sum(obtained_marks) / len(obtained_marks) if obtained_marks else 0.0
        highest_marks = max(obtained_marks) if obtained_marks else 0
        lowest_marks = min(obtained_marks) if obtained_marks else 0
        
        passed_students = len([m for m in marks if m.percentage and m.percentage >= 40])
        pass_percentage = (passed_students * 100.0 / appeared_students) if appeared_students > 0 else 0.0
        
        # Grade distribution
        grade_dist = {}
        for mark in marks:
            if mark.grade:
                grade_dist[mark.grade] = grade_dist.get(mark.grade, 0) + 1
        
        return {
            "total_students": total_students,
            "appeared_students": appeared_students,
            "average_marks": avg_marks,
            "highest_marks": highest_marks,
            "lowest_marks": lowest_marks,
            "pass_percentage": pass_percentage,
            "grade_distribution": grade_dist
        }