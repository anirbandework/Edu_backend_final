from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..base import Base

class PagePermission(Base):
    __tablename__ = "page_permissions"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False, index=True)
    
    # Page Information
    page_id = Column(String(100), nullable=False)  # e.g., "student_dashboard", "teacher_management"
    page_name = Column(String(100), nullable=False)  # e.g., "Student Dashboard", "Teacher Management"
    page_path = Column(String(200), nullable=False)  # e.g., "/student/dashboard", "/admin/teachers"
    page_icon = Column(String(50), nullable=True)  # e.g., "dashboard", "people"
    page_category = Column(String(50), nullable=True)  # e.g., "dashboard", "management", "academic"
    
    # Permissions
    can_view = Column(Boolean, default=True, nullable=False)
    can_create = Column(Boolean, default=False, nullable=False)
    can_edit = Column(Boolean, default=False, nullable=False)
    can_delete = Column(Boolean, default=False, nullable=False)
    can_export = Column(Boolean, default=False, nullable=False)
    can_import = Column(Boolean, default=False, nullable=False)
    
    # Additional metadata
    custom_permissions = Column(JSON, nullable=True)  # For page-specific permissions
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    tenant = relationship("Tenant")
    role = relationship("Role")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('tenant_id', 'role_id', 'page_id', name='uq_tenant_role_page'),
        Index('idx_page_permission_tenant_role', 'tenant_id', 'role_id'),
        Index('idx_page_permission_active', 'is_active'),
    )