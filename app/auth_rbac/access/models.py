"""RBAC tables (module/tab model).  Self-contained: a fresh `rbac_role` plus the
tenant-ceiling and role permission tables. Assignment is a `rbac_role_id` column
declared on the school_authorities / teachers / students ORM models (FK ->
rbac_roles, SET NULL); database_compare/migrations.py owns its index + the
idempotent ALTER for already-existing databases.
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class RbacRole(Base):
    __tablename__ = "rbac_roles"

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    role_name = Column(String(80), nullable=False)
    role_key = Column(String(80), nullable=False)
    user_type = Column(String(20), nullable=False)  # school_authority | teacher | student
    description = Column(String(255), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)  # auto-assigned to new users of this type
    created_by = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_type", "role_key", name="uq_rbac_role_tenant_type_key"),
    )


class TenantModulePermission(Base):
    """Tier-0: which modules a tenant may use, per audience (super-admin ceiling)."""
    __tablename__ = "tenant_module_permissions"

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    module_key = Column(String(60), nullable=False)
    # The audience columns below are the DISTRIBUTABLE org ceiling — which pages
    # the admin may hand out to teacher/student/staff roles ("what they paid for").
    authority_enabled = Column(Boolean, default=True, nullable=False)
    teacher_enabled = Column(Boolean, default=True, nullable=False)
    student_enabled = Column(Boolean, default=True, nullable=False)
    # admin_enabled is a SEPARATE ceiling: which pages the ADMIN (school authority)
    # sees in their OWN sidebar/toolset. Independent of the distributable columns.
    # Default ON so existing orgs keep today's "admin sees everything" behaviour.
    admin_enabled = Column(Boolean, default=True, nullable=False)
    configured_by = Column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "module_key", name="uq_tenant_module"),
    )


class TenantTabPermission(Base):
    """Tier-0: tab-level tenant ceiling."""
    __tablename__ = "tenant_tab_permissions"

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    module_key = Column(String(60), nullable=False)
    tab_key = Column(String(60), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    configured_by = Column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "module_key", "tab_key", name="uq_tenant_tab"),
    )


class RoleModulePermission(Base):
    """Tier-1: which modules a role enables (<= tenant ceiling)."""
    __tablename__ = "role_module_permissions"

    role_id = Column(UUID(as_uuid=True), ForeignKey("rbac_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    module_key = Column(String(60), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    configured_by = Column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("role_id", "module_key", name="uq_role_module"),
    )


class RoleTabPermission(Base):
    """Tier-1: tab-level role permission."""
    __tablename__ = "role_tab_permissions"

    role_id = Column(UUID(as_uuid=True), ForeignKey("rbac_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    module_key = Column(String(60), nullable=False)
    tab_key = Column(String(60), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    configured_by = Column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("role_id", "module_key", "tab_key", name="uq_role_tab"),
    )


class RoleCreatableRole(Base):
    """Delegation: a holder of `role_id` may create users assigned to
    `creatable_role_id`. Lets an admin hand user-creation to e.g. a Principal or
    HOD role without granting full admin."""
    __tablename__ = "role_creatable_roles"

    role_id = Column(UUID(as_uuid=True), ForeignKey("rbac_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    creatable_role_id = Column(UUID(as_uuid=True), ForeignKey("rbac_roles.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("role_id", "creatable_role_id", name="uq_role_creatable"),
    )
