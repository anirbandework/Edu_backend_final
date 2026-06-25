# app/models/tenant_specific/teacher.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...models.base import Base  # Updated import path

class Teacher(Base):
    __tablename__ = "teachers"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Basic Information
    teacher_id = Column(String(20), nullable=False, index=True)
    gender = Column(String(10), nullable=True)
    
    # New individual fields (optional, can be null if using JSON)
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    email = Column(String(100), nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)  # bcrypt; null = login disabled until set
    phone = Column(String(20), nullable=True)
    date_of_birth = Column(DateTime, nullable=True)
    address = Column(String(500), nullable=True)
    position = Column(String(100), nullable=True)
    joining_date = Column(DateTime, nullable=True)
    role = Column(String(20), default="teacher", nullable=False)
    # RBAC: assigned module/tab role (nullable; FK -> rbac_roles, SET NULL on delete).
    # Index ix_teachers_rbac_role is owned by database_compare/migrations.py.
    rbac_role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rbac_roles.id", ondelete="SET NULL", name="fk_teachers_rbac_role"),
        nullable=True,
    )
    qualification = Column(String(500), nullable=True)
    experience_years = Column(Integer, default=0)
    
    # Original JSON fields (kept for backward compatibility)
    teacher_details = Column(JSON)
    personal_info = Column(JSON)  # Contains all personal details
    contact_info = Column(JSON)   # Contains contact information
    family_info = Column(JSON)    # Contains family details
    qualifications = Column(JSON)         # Education and certifications
    employment = Column(JSON)            # Job details and salary
    academic_responsibilities = Column(JSON)  # Teaching assignments
    timetable = Column(JSON)             # Weekly schedule
    performance_evaluation = Column(JSON) # Performance data
    
    # Status
    status = Column(String(20), default="active", nullable=False)
    last_login = Column(DateTime)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="teachers")
    teacher_timetables = relationship("TeacherTimetable", back_populates="teacher_ref")
