"""Timetable — Phase 1. The recurring weekly schedule: a set of SLOTS per class.

A slot renders as a school period, a college lecture, a coaching batch slot, or a tutor's
bookable 1:1 — same table, org terminology varies. Each slot optionally carries a subject
and an INSTRUCTOR-capable member (capability-driven, never a hardcoded teacher). This is
what will drive per-period attendance + the "my classes today" flow.

See important_documents/MODULE_MASTER_PLAN.md §4.2.
"""
from sqlalchemy import Column, String, Integer, Time, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="SET NULL"),
                        nullable=True)
    # Must be an instructor/class_head-capable member (enforced in the service).
    instructor_member_id = Column(UUID(as_uuid=True),
                                  ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    weekday = Column(Integer, nullable=False)  # 0 = Monday … 6 = Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    room = Column(String(60), nullable=True)

    __table_args__ = (
        Index("ix_timetable_class_day", "class_id", "weekday", "is_deleted"),
        Index("ix_timetable_org_day", "organisation_id", "weekday", "is_deleted"),
    )
