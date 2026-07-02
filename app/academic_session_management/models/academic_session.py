"""AcademicSession — the time axis (school year / college semester / coaching batch-cycle
/ tutoring term) that every academic record (attendance, fees, marks) is scoped to.

Phase-0 spine. See important_documents/MODULE_MASTER_PLAN.md §3.1.
"""
from sqlalchemy import Column, String, Date, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class AcademicSession(Base):
    __tablename__ = "academic_sessions"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    name = Column(String(120), nullable=False)          # "2026-27" / "Fall 2026" / "Jan–Jun Batch"
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    # Exactly one session per organisation is the "current" one (enforced in the service).
    is_current = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_academic_sessions_org_active", "organisation_id", "is_deleted"),
    )
