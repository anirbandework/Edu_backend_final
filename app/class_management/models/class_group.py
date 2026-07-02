"""ClassGroup — the generic people-container that renders as Class/Section (school),
Programme/Course (college), or Batch (coaching) via `kind_label` + the org terminology
map. A private tutor gets an auto-created class-of-one. Self-referencing tree (`parent_id`)
so any nesting depth (Class→Section, Programme→Course→Section) is the same mechanism.

ClassMembership joins a `members` row into a class with a `capacity` — a participant
CAPABILITY key (instructor | class_head | learner) derived from the member's dynamic role,
NOT a hardcoded student/teacher/assistant enum. So a "Coach"-role member joins as
`instructor`, a "Trainee" as `learner`, with no school vocabulary baked in. NULL capacity =
attached without an academic role (e.g. office staff). See CONNECTIONS_AND_FLOW.md §3.2.

NOTE on naming: the table/key is `classes` (NOT `groups`) — the institution-GROUP tenant
layer already owns `group_management`/`groups`. The user-facing label stays generic via
`kind_label` + terminology, so "Class" here still displays as Batch/Course/etc.

Phase-0 spine. See important_documents/MODULE_MASTER_PLAN.md §3.2.
"""
from sqlalchemy import Column, String, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class ClassGroup(Base):
    __tablename__ = "classes"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True),
                        ForeignKey("academic_sessions.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    # Self-reference: Class 9 -> 9-A, or Programme -> Course -> Section.
    parent_id = Column(UUID(as_uuid=True),
                       ForeignKey("classes.id", ondelete="SET NULL"),
                       nullable=True, index=True)
    name = Column(String(120), nullable=False)
    # The org-type label this class is presented as ("Class", "Section", "Batch", "Course").
    kind_label = Column(String(40), nullable=True)

    __table_args__ = (
        Index("ix_classes_org_active", "organisation_id", "is_deleted"),
        # Accelerates the common "classes in this session" filter.
        Index("ix_classes_org_session", "organisation_id", "session_id", "is_deleted"),
    )


class ClassMembership(Base):
    __tablename__ = "class_members"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    member_id = Column(UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    # Participant capability key (instructor | class_head | learner) derived from the
    # member's dynamic role, or NULL. NEVER a hardcoded student/teacher/assistant value.
    capacity = Column(String(20), nullable=True)

    __table_args__ = (
        Index("ix_class_members_class", "class_id", "is_deleted"),
        Index("ix_class_members_member", "member_id", "is_deleted"),
        # A member belongs to a class at most once (among non-deleted rows). Their
        # capacity comes from their role, so there is one membership per (class, member).
        Index("uq_class_member_active", "class_id", "member_id",
              unique=True, postgresql_where=text("is_deleted = false")),
    )
