# app/models/tenant_specific/exam_management.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Text, Enum, Index, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from ...models.base import Base
import enum



class ExamStatus(enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RESULTS_PUBLISHED = "results_published"

class MarkingStatus(enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VERIFIED = "verified"
    PUBLISHED = "published"

class Exam(Base):
    __tablename__ = "exams"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)  # School authority/teacher
    
    # Basic Information
    exam_name = Column(String(200), nullable=False, index=True)
    exam_code = Column(String(50), nullable=False, index=True)
    exam_type = Column(String(50), nullable=False, index=True)
    description = Column(Text)
    
    # Academic Context
    academic_year = Column(String(10), nullable=False, index=True)
    term = Column(String(20), index=True)
    subject = Column(String(100), index=True)
    grade_levels = Column(JSON)  # [9, 10, 11] - which grades
    
    # Timing
    exam_date = Column(DateTime, index=True)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration_minutes = Column(Integer)
    
    # Configuration - Flexible JSON for different schools
    exam_config = Column(JSON)  # Custom fields per school
    marking_scheme = Column(JSON)  # Flexible marking configuration
    grading_criteria = Column(JSON)  # Custom grading rules
    
    # Status and Publishing
    status = Column(String(50), default="draft", nullable=False, index=True)
    is_published = Column(Boolean, default=False, index=True)
    published_at = Column(DateTime)
    published_by = Column(UUID(as_uuid=True))
    
    # Statistics
    total_students = Column(Integer, default=0)
    completed_markings = Column(Integer, default=0)
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('tenant_id', 'exam_code', 'academic_year', name='uq_exam_code_year'),
        Index('idx_exam_tenant_status', 'tenant_id', 'status'),
        Index('idx_exam_date_type', 'exam_date', 'exam_type'),
        Index('idx_exam_academic', 'tenant_id', 'academic_year', 'term'),
    )
    
    # Relationships
    tenant = relationship("Tenant")
    exam_classes = relationship("ExamClass", back_populates="exam", cascade="all, delete-orphan")
    student_marks = relationship("StudentExamMark", back_populates="exam", cascade="all, delete-orphan")

class ExamClass(Base):
    __tablename__ = "exam_classes"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True)
    
    # Class-specific configuration
    class_config = Column(JSON)  # Class-specific exam settings
    max_marks = Column(Integer)
    passing_marks = Column(Integer)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('exam_id', 'class_id', name='uq_exam_class'),
        Index('idx_exam_class_tenant', 'tenant_id', 'exam_id'),
    )
    
    # Relationships
    tenant = relationship("Tenant")
    exam = relationship("Exam", back_populates="exam_classes")
    class_ref = relationship("ClassModel")

class StudentExamMark(Base):
    __tablename__ = "student_exam_marks"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id"), nullable=False, index=True)
    # The mark's subject is a MEMBER (the enrolled student), not the legacy students table.
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True)
    
    # Marking Information
    marks_data = Column(JSON, nullable=False)  # Flexible marking structure
    total_marks = Column(Integer)
    obtained_marks = Column(Integer)
    percentage = Column(Integer)
    grade = Column(String(5))
    
    # Status and Tracking
    marking_status = Column(String(50), default="pending", nullable=False, index=True)
    marked_by = Column(UUID(as_uuid=True), index=True)
    marked_at = Column(DateTime)
    verified_by = Column(UUID(as_uuid=True))
    verified_at = Column(DateTime)
    
    # Additional Information
    remarks = Column(Text)
    attendance_status = Column(String(20), default="present")  # present, absent, late
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('exam_id', 'member_id', name='uq_member_exam_mark'),
        Index('idx_marks_tenant_exam', 'tenant_id', 'exam_id'),
        Index('idx_marks_member', 'member_id', 'exam_id'),
        Index('idx_marks_status', 'marking_status', 'exam_id'),
        Index('idx_marks_class', 'class_id', 'exam_id'),
        CheckConstraint('obtained_marks >= 0', name='ck_obtained_marks_positive'),
        CheckConstraint('percentage >= 0 AND percentage <= 100', name='ck_percentage_valid'),
    )
    
    # Relationships
    tenant = relationship("Tenant")
    exam = relationship("Exam", back_populates="student_marks")
    member = relationship("Member")
    class_ref = relationship("ClassModel")

class ExamTemplate(Base):
    __tablename__ = "exam_templates"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    
    # Template Information
    template_name = Column(String(100), nullable=False)
    template_type = Column(String(50), nullable=False)
    description = Column(Text)
    
    # Template Configuration
    template_config = Column(JSON)  # Reusable exam configuration
    marking_template = Column(JSON)  # Reusable marking scheme
    
    # Usage
    is_active = Column(Boolean, default=True)
    usage_count = Column(Integer, default=0)
    
    # Relationships
    tenant = relationship("Tenant")

class BulkMarkingBatch(Base):
    __tablename__ = "bulk_marking_batches"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id"), nullable=False, index=True)
    uploaded_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Batch Information
    batch_name = Column(String(100), nullable=False)
    file_name = Column(String(200))
    file_path = Column(String(500))
    
    # Processing Status
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    
    # Results
    processing_log = Column(JSON)
    error_details = Column(JSON)
    
    # Timing
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Relationships
    tenant = relationship("Tenant")
    exam = relationship("Exam")