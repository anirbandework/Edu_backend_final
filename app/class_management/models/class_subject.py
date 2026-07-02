"""Subject ↔ Class ↔ Instructor links.

Connects the (otherwise island) subjects to classes and to the people who teach them —
WITHOUT any hardcoded teacher concept. Two tables:

  • ClassSubject   (class_id, subject_id)             — which subjects a class studies.
  • SubjectTeacher (class_id, subject_id, member_id)  — who instructs that subject in that
                                                        class. The member's role MUST carry
                                                        the 'instructor' capability (enforced
                                                        in the service, never by role name).

Schema is reserved now so Phase-1 timetable/attendance build on it unchanged. See
important_documents/CONNECTIONS_AND_FLOW.md §3.3.
"""
from sqlalchemy import Column, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class ClassSubject(Base):
    __tablename__ = "class_subjects"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"),
                        nullable=False, index=True)

    __table_args__ = (
        # A subject is attached to a class at most once (among non-deleted rows).
        Index("uq_class_subject_active", "class_id", "subject_id",
              unique=True, postgresql_where=text("is_deleted = false")),
    )


class SubjectTeacher(Base):
    __tablename__ = "subject_teachers"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"),
                       nullable=False, index=True)

    __table_args__ = (
        # One instructor assigned to a (class, subject) at most once (non-deleted rows).
        Index("uq_subject_teacher_active", "class_id", "subject_id", "member_id",
              unique=True, postgresql_where=text("is_deleted = false")),
    )
