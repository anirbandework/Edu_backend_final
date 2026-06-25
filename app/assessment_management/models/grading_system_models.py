from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Numeric, Text, Enum
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from ...models.base import Base
import enum

class AssessmentType(enum.Enum):
    quiz = "quiz"
    test = "test"
    exam = "exam"
    homework = "homework"
    assignment = "assignment"
    project = "project"

class AssessmentStatus(enum.Enum):
    draft = "draft"
    published = "published"
    completed = "completed"
    graded = "graded"

class SubmissionStatus(enum.Enum):
    not_submitted = "not_submitted"
    submitted = "submitted"
    graded = "graded"

class Assessment(Base):
    __tablename__ = "assessments"
    
    # Foreign Keys - Use existing tables
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id"), nullable=False, index=True)  # Existing subjects table
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True)  # Existing classes table
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=False, index=True)   # Existing teachers table
    
    # Assessment Information
    assessment_title = Column(String(200), nullable=False)
    assessment_type = Column(Enum(AssessmentType), nullable=False)
    description = Column(Text)
    
    # Scheduling
    due_date = Column(DateTime)
    
    # Grading Information
    max_marks = Column(Numeric(8, 2), nullable=False)
    
    # Settings
    allow_late_submission = Column(Boolean, default=False)
    
    # Status
    status = Column(Enum(AssessmentStatus), default=AssessmentStatus.draft)
    
    # Academic Information
    academic_year = Column(String(10), nullable=False)
    
    # Relationships will be defined when needed
    submissions = relationship("AssessmentSubmission", back_populates="assessment")

class AssessmentSubmission(Base):
    __tablename__ = "assessment_submissions"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    assessment_id = Column(UUID(as_uuid=True), ForeignKey("assessments.id"), nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True)  # Existing students table
    
    # Submission Information
    submission_date = Column(DateTime)
    is_late = Column(Boolean, default=False)
    
    # Grading
    marks_obtained = Column(Numeric(8, 2))
    percentage = Column(Numeric(5, 2))
    grade_letter = Column(String(5))
    is_graded = Column(Boolean, default=False)
    
    # Feedback
    teacher_feedback = Column(Text)
    graded_by = Column(UUID(as_uuid=True), ForeignKey("teachers.id"))
    graded_date = Column(DateTime)
    
    # Status
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.not_submitted)
    
    # Relationships
    assessment = relationship("Assessment", back_populates="submissions")

class StudentGrade(Base):
    __tablename__ = "student_grades"
    
    # Foreign Keys - Use existing tables
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True)  # Existing students table
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id"), nullable=False, index=True)  # Existing subjects table
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True)  # Existing classes table
    
    # Academic Information
    academic_year = Column(String(10), nullable=False)
    term = Column(String(20))
    
    # Final Calculations
    percentage = Column(Numeric(5, 2))
    letter_grade = Column(String(5))
    gpa = Column(Numeric(3, 2))
    
    # Status
    is_final = Column(Boolean, default=False)
    
    # Tracking
    last_updated = Column(DateTime)
    calculated_by = Column(UUID(as_uuid=True), ForeignKey("teachers.id"))
    
    # Comments
    teacher_comments = Column(Text)
    
    # Relationships will be defined when needed

class GradeScale(Base):
    __tablename__ = "grade_scales"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Scale Information
    scale_name = Column(String(50), nullable=False)
    is_default = Column(Boolean, default=False)
    
    # Scale Configuration (stored as JSON)
    grade_ranges = Column(JSON)  # [{"min": 90, "max": 100, "letter": "A", "gpa": 4.0}, ...]
    
    # Applicability
    academic_year = Column(String(10), nullable=False)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Management
    created_by = Column(UUID(as_uuid=True), ForeignKey("school_authorities.id"))
    
    # Relationships will be defined when needed

class ReportCard(Base):
    __tablename__ = "report_cards"
    
    # Foreign Keys - Use existing tables
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True)  # Existing students table
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True)  # Existing classes table
    
    # Report Information
    report_period = Column(String(20), nullable=False)  # "Term 1", "Semester 1", etc.
    academic_year = Column(String(10), nullable=False)
    
    # Overall Performance
    total_subjects = Column(Integer)
    subjects_passed = Column(Integer)
    subjects_failed = Column(Integer)
    overall_percentage = Column(Numeric(5, 2))
    overall_gpa = Column(Numeric(3, 2))
    overall_grade = Column(String(5))
    
    # Subject-wise Grades (stored as JSON)
    subject_grades = Column(JSON)  # Detailed breakdown by subject
    
    # Comments
    class_teacher_comments = Column(Text)
    principal_comments = Column(Text)
    
    # Status
    is_published = Column(Boolean, default=False)
    published_date = Column(DateTime)
    
    # Generation Information
    generated_by = Column(UUID(as_uuid=True), ForeignKey("school_authorities.id"))
    generated_date = Column(DateTime)
    
    # Relationships will be defined when needed