# app/feedback_management/models/feedback.py
"""Feedback submitted by any user (student/teacher/admin/super-admin). Read and
triaged by the super-admin. user_id/organisation_id are plain UUIDs (no FK — the
submitter can live in any of several identity tables)."""
from sqlalchemy import Column, String, Text, Integer
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class Feedback(Base):
    __tablename__ = "feedback"

    organisation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_type = Column(String(30), nullable=False)   # the submitter's role
    user_name = Column(String(120), nullable=True)
    user_phone = Column(String(20), nullable=True)

    # suggestion | bug | complaint | appreciation | other
    feedback_type = Column(String(30), nullable=False, default="suggestion")
    rating = Column(Integer, nullable=True)          # optional 1-5
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)

    # pending | reviewed | resolved
    status = Column(String(20), nullable=False, default="pending", index=True)
