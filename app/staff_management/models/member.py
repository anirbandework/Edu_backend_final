"""Member — the UNIFIED identity table for every dynamic-role user an organisation
creates (faculty, principal, HOD, office staff, librarian, accountant, ...).

Unlike teachers/students/authorities, a staff user has no fixed canonical
behaviour: what they can see and do is defined entirely by the rbac_role assigned
to them (cross-section page grants + delegated user-creation). Login is by
phone+password, same as every other user.
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ...models.base import Base


class Member(Base):
    __tablename__ = "members"

    # The organisation this staff member belongs to (always scoped to one organisation).
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True)

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
    # Email OPTIONAL — login is phone+password. Uniqueness is enforced by a PARTIAL
    # unique index on live rows (uq_members_email_active, WHERE is_deleted=false) so a
    # soft-deleted member's email can be reused; the email trgm index covers search.
    email = Column(String(100), nullable=True)
    # Phone is the login id when set, but NULLABLE: a member can be created name-only
    # (e.g. an org's auto-created head/Principal) and get a phone later to enable login.
    phone = Column(String(20), nullable=True, index=True)
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
    # Tokens issued before this instant are rejected (set on password change/reset).
    sessions_invalidated_at = Column(DateTime(timezone=True), nullable=True)

    organisation = relationship("Organisation")
