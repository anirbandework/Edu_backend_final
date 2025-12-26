from sqlalchemy import Column, String, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..base import Base

class Role(Base):
    __tablename__ = "roles"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Role Information
    role_name = Column(String(50), nullable=False)
    subrole = Column(String(50), nullable=True)
    description = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    tenant = relationship("Tenant")
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")
    page_permissions = relationship("PagePermission", back_populates="role", cascade="all, delete-orphan")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('tenant_id', 'role_name', 'subrole', name='uq_tenant_role_subrole'),
        Index('idx_role_tenant_active', 'tenant_id', 'is_active'),
        Index('idx_role_name_active', 'role_name', 'is_active'),
    )