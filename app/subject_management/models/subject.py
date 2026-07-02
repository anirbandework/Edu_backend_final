"""Subject — the subject/course-content dimension (Math, Physics, "DSA"). Optional for
single-subject coaching/tutors. Linked to classes + teachers via the timetable later.

Phase-0 spine. See important_documents/MODULE_MASTER_PLAN.md §3.3.
"""
from sqlalchemy import Column, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class Subject(Base):
    __tablename__ = "subjects"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    name = Column(String(120), nullable=False)
    code = Column(String(40), nullable=True)

    __table_args__ = (
        Index("ix_subjects_org_active", "organisation_id", "is_deleted"),
    )
