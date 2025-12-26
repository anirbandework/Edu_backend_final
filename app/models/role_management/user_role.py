from sqlalchemy import Column, String, ForeignKey, UniqueConstraint, Index, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..base import Base
import enum

class UserType(enum.Enum):
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    SCHOOL_AUTHORITY = "SCHOOL_AUTHORITY"

class UserRole(Base):
    __tablename__ = "user_roles"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False, index=True)
    
    # User Information
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_type = Column(Enum(UserType), nullable=False)
    
    # Relationships
    tenant = relationship("Tenant")
    role = relationship("Role", back_populates="user_roles")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('user_id', name='uq_user_single_role'),
        Index('idx_user_role_tenant', 'tenant_id', 'user_id'),
        Index('idx_user_type_tenant', 'user_type', 'tenant_id'),
    )