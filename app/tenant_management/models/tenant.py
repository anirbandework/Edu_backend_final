# app/models/shared/tenant.py
"""Tenant (School) model definition."""
from sqlalchemy import Column, String, Integer, Numeric, ARRAY, Boolean, DateTime, UniqueConstraint, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates
from ...models.base import Base

class Tenant(Base):
    __tablename__ = "tenants"
    
    # Basic Information
    school_code = Column(String(10), unique=True, nullable=False, index=True)
    school_name = Column(String(200), nullable=False, index=True)
    address = Column(String(500), nullable=False)
    phone = Column(String(15), nullable=False)  # Removed redundant index
    email = Column(String(254), nullable=False)  # Standard email length, removed redundant index

    @validates('phone')
    def validate_phone(self, key, value):
        import re
        if not value or not re.match(r'^\+?\d{7,15}$', value):
            raise ValueError("Invalid phone number format")
        return value

    @validates('email')
    def validate_email(self, key, value):
        import re
        # Remove mailto: prefix if present
        if value and value.startswith('mailto:'):
            value = value[7:]
        if not value or not re.match(r'^[^@]+@[^@]+\.[^@]+$', value):
            raise ValueError("Invalid email address format")
        return value
    

    principal_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)  # Removed redundant index
    
    # Financial Information
    annual_tuition = Column(Numeric(10, 2), nullable=False)
    registration_fee = Column(Numeric(8, 2), nullable=False)
    charges_applied = Column(Boolean, default=False, nullable=False)
    charges_amount = Column(Numeric(10, 2), nullable=True)
    
    # Statistics with validation
    maximum_capacity = Column(Integer, nullable=False)
    
    # Academic Information
    school_type = Column(String(20), default="K-12")
    grade_levels = Column(ARRAY(String), nullable=False)
    established_year = Column(Integer)
    accreditation = Column(String(50))
    language_of_instruction = Column(String(20), default="English")

    # The admin (school_authority) who created/owns this school. NULL for legacy
    # schools created directly by the super-admin. FK + index live in migrations.
    owner_authority_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Soft delete (inherited from Base but explicitly defined for clarity)
    is_deleted = Column(Boolean, default=False, nullable=False)

    @validates('is_deleted')
    def validate_is_deleted(self, key, value):
        if value is None:
            return False
        return bool(value)
    
    # Relationships - optimized for 100k+ scale
    authorities = relationship("SchoolAuthority", back_populates="tenant", cascade="all, delete-orphan", lazy="dynamic")
    teachers = relationship("Teacher", back_populates="tenant", cascade="all, delete-orphan", lazy="dynamic")
    students = relationship("Student", back_populates="tenant", cascade="all, delete-orphan", lazy="dynamic")
    classes = relationship("ClassModel", back_populates="tenant", cascade="all, delete-orphan", lazy="dynamic")
    

    
    # Validation methods
    @validates('annual_tuition', 'registration_fee', 'charges_amount')
    def validate_financial(self, key, value):
        if value is None:
            return value
        try:
            if float(value) < 0:
                raise ValueError(f"{key} must be non-negative")
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"{key} must be a valid number")
        return value
    
    @validates('maximum_capacity')
    def validate_counts(self, key, value):
        if value is None:
            return value
        
        # Convert to integer
        try:
            int_value = int(value)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"{key} must be a valid integer")
        
        # Check positive for capacity
        if int_value <= 0:
            raise ValueError("maximum_capacity must be greater than 0")
        
        return int_value
    
    # Database constraints and indexes
    __table_args__ = (
        # Unique constraints
        UniqueConstraint('email', name='uq_tenant_email'),
        UniqueConstraint('phone', name='uq_tenant_phone'),
        UniqueConstraint('school_name', 'address', name='uq_tenant_school_name_address'),
        UniqueConstraint('school_code', name='uq_tenant_school_code'),
        
        # Financial constraints
        CheckConstraint('annual_tuition >= 0', name='ck_tuition_positive'),
        CheckConstraint('registration_fee >= 0', name='ck_fee_positive'),
        CheckConstraint('charges_amount >= 0', name='ck_charges_positive'),
        
        # Capacity constraints
        CheckConstraint('maximum_capacity > 0', name='ck_capacity_positive'),
        
        # Performance indexes for 100k+ scale
        Index('idx_active_code', 'is_active', 'school_code'),
        Index('idx_active_name', 'is_active', 'school_name'),
        Index('idx_email_active', 'email', 'is_active'),
        Index('idx_phone_active', 'phone', 'is_active'),
        Index('idx_created_at', 'created_at'),
        Index('idx_school_type_active', 'school_type', 'is_active'),
        Index('idx_deleted_active', 'is_deleted', 'is_active'),
    )

 