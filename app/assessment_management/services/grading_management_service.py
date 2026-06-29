from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, func, desc, select
from ...services.base_service import BaseService
from ..models.grading_system_models import (
    Assessment, AssessmentSubmission, StudentGrade, GradeScale, ReportCard,
    AssessmentType, AssessmentStatus, SubmissionStatus
)
from ...timetable_management.models.timetable import Subject
from ...class_management.models.class_model import ClassModel
from ...core.config_assessment import assessment_settings
import logging

logger = logging.getLogger(__name__)

class GradesService(BaseService[Assessment]):
    def __init__(self, db: AsyncSession):
        super().__init__(Assessment, db)
    
    async def create_assessment(self, assessment_data: dict) -> Assessment:
        """Create a new assessment using existing subject/class/teacher"""
        try:
            assessment = Assessment(**assessment_data)
            self.db.add(assessment)
            await self.db.commit()
            await self.db.refresh(assessment)
            return assessment
        except Exception as e:
            await self.db.rollback()
            raise e
    
    async def submit_assessment(
        self,
        assessment_id: UUID,
        student_id: UUID,
        submission_data: dict
    ) -> AssessmentSubmission:
        """Submit an assessment"""
        
        # Check if assessment exists and is published
        stmt = select(Assessment).where(
            and_(
                Assessment.id == assessment_id,
                Assessment.status == AssessmentStatus.published
            )
        )
        result = await self.db.execute(stmt)
        assessment = result.scalar_one_or_none()
        
        if not assessment:
            raise ValueError("Assessment not found or not published")
        
        # Check if late submission
        is_late = False
        if assessment.due_date and datetime.now() > assessment.due_date:
            if not assessment.allow_late_submission:
                logger.warning(f"Late submission attempted for assessment {assessment_id}")
                raise ValueError("Late submission not allowed")
            is_late = True
            logger.info(f"Late submission accepted for assessment {assessment_id}")
        
        submission = AssessmentSubmission(
            tenant_id=assessment.tenant_id,
            assessment_id=assessment_id,
            student_id=student_id,
            submission_date=datetime.now(),
            is_late=is_late,
            status=SubmissionStatus.submitted,
            **submission_data
        )
        
        self.db.add(submission)
        await self.db.commit()
        await self.db.refresh(submission)
        
        return submission
    
    async def grade_submission(
        self,
        submission_id: UUID,
        marks_obtained: Decimal,
        graded_by: UUID,
        feedback: Optional[str] = None
    ) -> AssessmentSubmission:
        """Grade an assessment submission"""
        
        stmt = select(AssessmentSubmission).where(AssessmentSubmission.id == submission_id)
        result = await self.db.execute(stmt)
        submission = result.scalar_one_or_none()
        
        if not submission:
            raise ValueError("Submission not found")
        
        # Get assessment details
        stmt = select(Assessment).where(Assessment.id == submission.assessment_id)
        result = await self.db.execute(stmt)
        assessment = result.scalar_one_or_none()
        
        # Calculate percentage
        percentage = (Decimal(str(marks_obtained)) / assessment.max_marks) * 100
        
        # Determine letter grade
        letter_grade = await self._calculate_letter_grade(
            percentage, assessment.tenant_id, assessment.academic_year
        )
        
        # Update submission
        submission.marks_obtained = marks_obtained
        submission.percentage = percentage
        submission.grade_letter = letter_grade
        submission.is_graded = True
        submission.teacher_feedback = feedback
        submission.graded_by = graded_by
        submission.graded_date = datetime.now()
        submission.status = SubmissionStatus.graded
        
        await self.db.commit()
        
        # Update student's overall grade for the subject
        await self._update_student_grade(
            submission.student_id, 
            assessment.subject_id, 
            assessment.class_id,
            assessment.academic_year
        )
        
        return submission
    
    async def _calculate_letter_grade(
        self, 
        percentage: Decimal, 
        tenant_id: UUID, 
        academic_year: str
    ) -> str:
        """Calculate letter grade based on percentage"""
        
        stmt = select(GradeScale).where(
            and_(
                GradeScale.tenant_id == tenant_id,
                GradeScale.academic_year == academic_year,
                GradeScale.is_default == True
            )
        )
        result = await self.db.execute(stmt)
        grade_scale = result.scalar_one_or_none()
        
        if not grade_scale:
            return "N/A"
        
        for range_data in grade_scale.grade_ranges:
            if range_data["min"] <= percentage <= range_data["max"]:
                return range_data["letter"]
        
        return "F"
    
    async def _update_student_grade(
        self, 
        student_id: UUID, 
        subject_id: UUID, 
        class_id: UUID,
        academic_year: str
    ):
        """Update student's overall grade for a subject"""
        
        # Get all submissions for this student and subject
        stmt = select(AssessmentSubmission).join(Assessment).where(
            and_(
                Assessment.subject_id == subject_id,
                Assessment.class_id == class_id,
                AssessmentSubmission.student_id == student_id,
                AssessmentSubmission.is_graded == True
            )
        )
        result = await self.db.execute(stmt)
        submissions = result.scalars().all()
        
        if not submissions:
            return
        
        # Calculate average percentage
        total_percentage = sum(float(s.percentage) for s in submissions)
        overall_percentage = total_percentage / len(submissions)
        
        # Get or create student grade record
        stmt = select(StudentGrade).where(
            and_(
                StudentGrade.student_id == student_id,
                StudentGrade.subject_id == subject_id,
                StudentGrade.class_id == class_id,
                StudentGrade.academic_year == academic_year
            )
        )
        result = await self.db.execute(stmt)
        student_grade = result.scalar_one_or_none()
        
        if not student_grade:
            # Get tenant_id from first submission
            tenant_id = submissions[0].tenant_id
            
            student_grade = StudentGrade(
                tenant_id=tenant_id,
                student_id=student_id,
                subject_id=subject_id,
                class_id=class_id,
                academic_year=academic_year
            )
            self.db.add(student_grade)
        
        # Update grade
        student_grade.percentage = overall_percentage
        student_grade.letter_grade = await self._calculate_letter_grade(
            overall_percentage, student_grade.tenant_id, academic_year
        )
        student_grade.gpa = await self._calculate_gpa(
            overall_percentage, student_grade.tenant_id, academic_year
        )
        student_grade.last_updated = datetime.now()
        
        await self.db.commit()
    
    async def _calculate_gpa(
        self, 
        percentage: Decimal, 
        tenant_id: UUID, 
        academic_year: str
    ) -> Decimal:
        """Calculate GPA based on percentage"""
        
        stmt = select(GradeScale).where(
            and_(
                GradeScale.tenant_id == tenant_id,
                GradeScale.academic_year == academic_year,
                GradeScale.is_default == True
            )
        )
        result = await self.db.execute(stmt)
        grade_scale = result.scalar_one_or_none()
        
        if not grade_scale:
            return Decimal("0.00")
        
        for range_data in grade_scale.grade_ranges:
            if range_data["min"] <= percentage <= range_data["max"]:
                return Decimal(str(range_data["gpa"]))
        
        return Decimal("0.00")
    
    async def get_student_grades(
        self,
        student_id: UUID,
        class_id: UUID,
        academic_year: Optional[str] = None
    ) -> List[StudentGrade]:
        """Get grades for a specific student in a class"""
        
        stmt = select(StudentGrade).where(
            and_(
                StudentGrade.student_id == student_id,
                StudentGrade.class_id == class_id
            )
        )
        
        if academic_year:
            stmt = stmt.where(StudentGrade.academic_year == academic_year)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def generate_report_card(
        self,
        student_id: UUID,
        class_id: UUID,
        report_period: str,
        academic_year: str
    ) -> ReportCard:
        """Generate report card for a student"""
        
        # Get student grades for the period
        student_grades = await self.get_student_grades(student_id, class_id, academic_year)
        
        if not student_grades:
            raise ValueError("No grades found for student")
        
        # Calculate overall statistics
        total_subjects = len(student_grades)
        subjects_passed = sum(1 for sg in student_grades if sg.percentage >= 60)
        subjects_failed = total_subjects - subjects_passed
        
        # Calculate overall percentage and GPA
        total_percentage = sum(float(sg.percentage) for sg in student_grades)
        overall_percentage = total_percentage / total_subjects if total_subjects > 0 else 0
        
        total_gpa = sum(float(sg.gpa) for sg in student_grades)
        overall_gpa = total_gpa / total_subjects if total_subjects > 0 else 0
        
        overall_grade = await self._calculate_letter_grade(
            overall_percentage, student_grades[0].tenant_id, academic_year
        )
        
        # Prepare subject-wise grades
        subject_grades = []
        for sg in student_grades:
            # Get subject details
            stmt = select(Subject).where(Subject.id == sg.subject_id)
            result = await self.db.execute(stmt)
            subject = result.scalar_one_or_none()
            
            if subject:
                subject_grades.append({
                    "subject_name": subject.subject_name,
                    "subject_code": subject.subject_code,
                    "percentage": float(sg.percentage),
                    "letter_grade": sg.letter_grade,
                    "gpa": float(sg.gpa)
                })
        
        # Create report card
        report_card = ReportCard(
            tenant_id=student_grades[0].tenant_id,
            student_id=student_id,
            class_id=class_id,
            report_period=report_period,
            academic_year=academic_year,
            total_subjects=total_subjects,
            subjects_passed=subjects_passed,
            subjects_failed=subjects_failed,
            overall_percentage=overall_percentage,
            overall_gpa=overall_gpa,
            overall_grade=overall_grade,
            subject_grades=subject_grades,
            generated_date=datetime.now()
        )
        
        self.db.add(report_card)
        await self.db.commit()
        await self.db.refresh(report_card)
        
        return report_card
    
    async def create_default_grade_scale(self, tenant_id: UUID, academic_year: str):
        """Create default grade scale for the tenant"""
        stmt = select(GradeScale).where(
            and_(
                GradeScale.tenant_id == tenant_id,
                GradeScale.academic_year == academic_year,
                GradeScale.is_default == True
            )
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if not existing:
            default_scale = GradeScale(
                tenant_id=tenant_id,
                scale_name="Standard Grade Scale",
                academic_year=academic_year,
                is_default=True,
                grade_ranges=[
                    {"min": 90, "max": 100, "letter": "A", "gpa": 4.0},
                    {"min": 80, "max": 89, "letter": "B", "gpa": 3.0},
                    {"min": 70, "max": 79, "letter": "C", "gpa": 2.0},
                    {"min": 60, "max": 69, "letter": "D", "gpa": 1.0},
                    {"min": 0, "max": 59, "letter": "F", "gpa": 0.0}
                ]
            )
            self.db.add(default_scale)
            await self.db.commit()