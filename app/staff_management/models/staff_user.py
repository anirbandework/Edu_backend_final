"""StaffUser — the UNIFIED identity table for every dynamic-role user a school
creates (faculty, principal, HOD, office staff, librarian, accountant, ...).

Unlike teachers/students/school_authorities, a staff user has no fixed canonical
behaviour: what they can see and do is defined entirely by the rbac_role assigned
to them (cross-section page grants + delegated user-creation). Login is by
phone+password, same as every other user.
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ...models.base import Base


class StaffUser(Base):
    __tablename__ = "staff_users"

    # The school this staff member belongs to (always scoped to one tenant).
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    # The dynamic role that defines this user's pages + creation rights.
    rbac_role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rbac_roles.id", ondelete="SET NULL", name="fk_staff_rbac_role"),
        nullable=True,
        index=True,
    )

    # Human-readable code, e.g. STF-0001 (generated).
    staff_id = Column(String(20), nullable=True, index=True)

    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    # Email OPTIONAL — login is phone+password. Unique holds for non-null values.
    email = Column(String(100), nullable=True, unique=True, index=True)
    phone = Column(String(20), nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # bcrypt; null = login disabled

    # Free-text designation shown in the UI ("Faculty", "Principal", "HOD"...).
    position = Column(String(100), nullable=True)

    date_of_birth = Column(DateTime, nullable=True)
    gender = Column(String(10), nullable=True)
    address = Column(String(500), nullable=True)

    status = Column(String(20), default="active", nullable=False)  # active | inactive
    role = Column(String(20), default="staff", nullable=False)     # canonical bucket

    created_by = Column(UUID(as_uuid=True), nullable=True)
    profile = Column(JSON)
    last_login = Column(DateTime, nullable=True)
    experience_years = Column(Integer, default=0)

    tenant = relationship("Tenant")
