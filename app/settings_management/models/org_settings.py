"""OrgSettings — the per-organisation control panel that makes ONE UI read naturally for
any org type. Holds the terminology label-map (class↔batch↔course) and academic config
(attendance_mode, grading scheme, …). `org_type` itself lives on the organisations row;
this layer carries the labels + behaviour an admin can override.

One row per organisation (unique organisation_id). Phase-0 spine.
See important_documents/MODULE_MASTER_PLAN.md §3.4.
"""
from sqlalchemy import Column, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class OrgSettings(Base):
    __tablename__ = "org_settings"

    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"),
                             nullable=False, unique=True, index=True)
    # {"group":"Batch","subgroup":"Sub-batch","session":"Term","subject":"Subject",
    #  "member":"Student","teacher":"Tutor"}
    terminology = Column(JSON)
    # {"attendance_mode":"per_period"|"daily", "grading_scheme":"marks"|"gpa"|"pass_fail", ...}
    config = Column(JSON)
