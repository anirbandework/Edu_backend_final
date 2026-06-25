# app/models/tenant_specific/student.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...models.base import Base

class Student(Base):  # Changed from BaseModel to Base
    __tablename__ = "students"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Basic Information
    student_id = Column(String(20), nullable=False, index=True)
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    email = Column(String(100), index=True)
    password_hash = Column(String(255), nullable=True)  # bcrypt; null = login disabled until set
    phone = Column(String(20), nullable=True, index=True)
    date_of_birth = Column(DateTime, nullable=True)
    address = Column(String(500), nullable=True)
    gender = Column(String(10), nullable=True)
    
    # Academic Information
    role = Column(String(20), default="student", nullable=False)
    # RBAC: assigned module/tab role (nullable; FK -> rbac_roles, SET NULL on delete).
    # Index ix_students_rbac_role is owned by database_compare/migrations.py.
    rbac_role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rbac_roles.id", ondelete="SET NULL", name="fk_students_rbac_role"),
        nullable=True,
    )
    status = Column(String(20), default="active", nullable=False)
    admission_number = Column(String(20), nullable=True, index=True)
    roll_number = Column(String(20))
    grade_level = Column(Integer, nullable=True)
    section = Column(String(10))
    academic_year = Column(String(10), nullable=True)
    
    # Extended Information (JSON fields for flexibility)
    parent_info = Column(JSON)           # Parent/guardian details
    health_medical_info = Column(JSON)   # Medical information
    emergency_information = Column(JSON) # Emergency contacts
    behavioral_disciplinary = Column(JSON) # Behavioral records
    extended_academic_info = Column(JSON)  # Academic history
    enrollment_details = Column(JSON)     # Enrollment information
    financial_info = Column(JSON)         # Fee and scholarship details
    extracurricular_social = Column(JSON) # Activities and interests
    attendance_engagement = Column(JSON)  # Attendance data
    additional_metadata = Column(JSON)    # Photos and other data
    
    last_login = Column(DateTime)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="students")
    enrollments = relationship("Enrollment", back_populates="student")
    # grades = relationship("Grade", back_populates="student")
    # attendances = relationship("Attendance", back_populates="student")
    # chat_rooms = relationship("ChatRoom", back_populates="student")
