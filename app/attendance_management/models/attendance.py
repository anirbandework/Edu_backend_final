"""Attendance — Phase 1 keystone.

Attendance is marked per CLASS SESSION (an occurrence of a class on a date), NOT per
class, because the same class is taught repeatedly and by different people. The roster is
the class's LEARNER-capacity members (capability-driven, never a hardcoded "student"), and
only an instructor/class_head-capable member (or an admin) records it.

`org_settings.config.attendance_mode` switches behaviour on the SAME tables:
  • daily       → one session per (class, date); subject_id NULL.
  • per_period  → one session per (class, subject, date).

See important_documents/MODULE_MASTER_PLAN.md §4.1 and CONNECTIONS_AND_FLOW.md.
"""
from sqlalchemy import (Column, String, Date, DateTime, Boolean, ForeignKey, Index, text, func)
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class ClassSession(Base):
    __tablename__ = "class_sessions"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    # NULL in daily mode; the taught subject in per_period mode.
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="SET NULL"),
                        nullable=True)
    # The academic session (term/year) this falls in — for "attendance this term" reports.
    academic_session_id = Column(UUID(as_uuid=True),
                                 ForeignKey("academic_sessions.id", ondelete="SET NULL"),
                                 nullable=True)
    # Who taught/recorded it — must be an instructor/class_head-capable member (enforced in
    # the service). NULL when an admin records without naming an instructor.
    instructor_member_id = Column(UUID(as_uuid=True),
                                  ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    date = Column(Date, nullable=False)
    locked = Column(Boolean, default=False, nullable=False)  # frozen — no further edits

    __table_args__ = (
        Index("ix_class_sessions_class_date", "class_id", "date", "is_deleted"),
        Index("ix_class_sessions_org_active", "organisation_id", "is_deleted"),
        # One session per (class, date, subject) among live rows. The COALESCE makes the
        # daily case (subject NULL) collapse to one-per-(class,date) too. Built in
        # migrations.py because it is an expression index.
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    class_session_id = Column(UUID(as_uuid=True),
                              ForeignKey("class_sessions.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    # present | absent | late | excused | leave  (validated in the service)
    status = Column(String(12), nullable=False, default="present")
    marked_by = Column(UUID(as_uuid=True), nullable=True)
    marked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    __table_args__ = (
        # One record per learner per session (among non-deleted rows).
        Index("uq_attendance_record_active", "class_session_id", "member_id",
              unique=True, postgresql_where=text("is_deleted = false")),
    )
