"""RBAC tables (module/tab model).  Self-contained: a fresh `rbac_role` plus the
organisation-ceiling and role permission tables. Assignment is a `rbac_role_id` column
declared on the authorities / teachers / students ORM models (FK ->
rbac_roles, SET NULL); database_compare/migrations.py owns its index + the
idempotent ALTER for already-existing databases.
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from ...models.base import Base


class RbacRole(Base):
    __tablename__ = "rbac_roles"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)
    role_name = Column(String(80), nullable=False)
    role_key = Column(String(80), nullable=False)
    user_type = Column(String(20), nullable=False)  # authority | teacher | student
    description = Column(String(255), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)  # auto-assigned to new users of this type
    created_by = Column(UUID(as_uuid=True), nullable=True)
    # Admin-defined extra fields collected when adding a user to this role (grade,
    # parent name, address, ...). A JSON list of {key,label,type,required,options}.
    # Filled values live on members.profile['custom_fields']. See access/custom_fields.py.
    custom_fields = Column(JSONB, nullable=False, default=list, server_default="[]")
    # Behaviour flags describing what this role's members DO in academic flows
    # (learner | instructor | class_head | guardian | admin_staff). A JSON list of
    # capability keys from access/capabilities.py. Modules query "which roles have
    # capability X" instead of hardcoding teacher/student. Orthogonal to page grants.
    capabilities = Column(JSONB, nullable=False, default=list, server_default="[]")

    __table_args__ = (
        UniqueConstraint("organisation_id", "user_type", "role_key", name="uq_rbac_role_organisation_type_key"),
    )


class GroupModulePermission(Base):
    """Tier-0 ceiling, per INSTITUTION GROUP (super-admin controls). Two flags,
    both applying to EVERY organisation in the group:
      • role_enabled  — the page is in the group's POOL: admins may grant it to
                        staff roles ("what the group paid for").
      • admin_enabled — the page shows in the ADMINS' own sidebar/toolset.
    Default ON so a new group starts permissive until the super-admin revokes."""
    __tablename__ = "group_module_permissions"

    group_id = Column(UUID(as_uuid=True), ForeignKey("institution_groups.id"), nullable=False, index=True)
    module_key = Column(String(60), nullable=False)
    role_enabled = Column(Boolean, default=True, nullable=False)
    admin_enabled = Column(Boolean, default=True, nullable=False)
    configured_by = Column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("group_id", "module_key", name="uq_group_module"),
    )


class GroupTabPermission(Base):
    """Tier-0: tab-level group ceiling (for pages that have sub-tabs)."""
    __tablename__ = "group_tab_permissions"

    group_id = Column(UUID(as_uuid=True), ForeignKey("institution_groups.id"), nullable=False, index=True)
    module_key = Column(String(60), nullable=False)
    tab_key = Column(String(60), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    configured_by = Column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("group_id", "module_key", "tab_key", name="uq_group_tab"),
    )


class RoleModulePermission(Base):
    """Tier-1: which modules a role enables (<= organisation ceiling)."""
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
