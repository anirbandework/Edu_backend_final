"""SettingsService — per-organisation terminology + academic config (the control panel
that adapts one UI to any org type). `org_type` is read from the organisations row; this
provides the smart DEFAULTS per type, plus the admin's overrides."""
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.org_settings import OrgSettings

# Smart defaults per org_type — terminology labels + academic config. The admin can
# override any of these; this is just what each type starts with.
_PRESETS = {
    "school":   {"terminology": {"group": "Class", "subgroup": "Section", "session": "Academic Year",
                                 "subject": "Subject", "member": "Student", "teacher": "Teacher"},
                 "config": {"attendance_mode": "per_period", "grading_scheme": "marks"}},
    "college":  {"terminology": {"group": "Course", "subgroup": "Section", "session": "Semester",
                                 "subject": "Subject", "member": "Student", "teacher": "Faculty"},
                 "config": {"attendance_mode": "per_period", "grading_scheme": "gpa"}},
    "coaching": {"terminology": {"group": "Batch", "subgroup": "Sub-batch", "session": "Batch Cycle",
                                 "subject": "Subject", "member": "Student", "teacher": "Tutor"},
                 "config": {"attendance_mode": "per_period", "grading_scheme": "marks"}},
    "tutor":    {"terminology": {"group": "Group", "subgroup": "Group", "session": "Term",
                                 "subject": "Subject", "member": "Student", "teacher": "Tutor"},
                 "config": {"attendance_mode": "daily", "grading_scheme": "marks"}},
}
_DEFAULT = {"terminology": {"group": "Group", "subgroup": "Sub-group", "session": "Session",
                            "subject": "Subject", "member": "Member", "teacher": "Teacher"},
            "config": {"attendance_mode": "daily", "grading_scheme": "marks"}}


class SettingsService:
    @staticmethod
    async def _org_type(db: AsyncSession, organisation_id) -> Optional[str]:
        row = (await db.execute(
            text("SELECT org_type FROM organisations WHERE id = :id"), {"id": str(organisation_id)}
        )).first()
        return row[0] if row else None

    @staticmethod
    def _preset_for(org_type: Optional[str]) -> dict:
        return _PRESETS.get((org_type or "").lower(), _DEFAULT)

    @staticmethod
    async def get(db: AsyncSession, organisation_id) -> dict:
        row = (await db.execute(
            select(OrgSettings).where(OrgSettings.organisation_id == organisation_id)
        )).scalar_one_or_none()
        org_type = await SettingsService._org_type(db, organisation_id)
        preset = SettingsService._preset_for(org_type)
        return {
            "org_type": org_type,
            "terminology": (row.terminology if row and row.terminology else None) or preset["terminology"],
            "config": (row.config if row and row.config else None) or preset["config"],
            "is_customised": bool(row),
        }

    @staticmethod
    async def _get_or_create_row(db: AsyncSession, organisation_id) -> OrgSettings:
        """Fetch the org's settings row, creating it if absent. Handles the
        concurrent-insert race on the unique organisation_id: if two requests both
        find no row and both INSERT, the loser catches the IntegrityError and reuses
        the row the winner created (instead of a 500)."""
        row = (await db.execute(
            select(OrgSettings).where(OrgSettings.organisation_id == organisation_id)
        )).scalar_one_or_none()
        if row is not None:
            return row
        row = OrgSettings(organisation_id=organisation_id)
        db.add(row)
        try:
            await db.flush()  # surface the unique(organisation_id) violation now
        except IntegrityError:
            await db.rollback()
            row = (await db.execute(
                select(OrgSettings).where(OrgSettings.organisation_id == organisation_id)
            )).scalar_one_or_none()
            if row is None:
                raise
        return row

    @staticmethod
    async def upsert(db: AsyncSession, organisation_id, *, terminology=None, config=None) -> dict:
        row = await SettingsService._get_or_create_row(db, organisation_id)
        if terminology is not None:
            row.terminology = dict(terminology)
        if config is not None:
            row.config = dict(config)
        await db.commit()
        return await SettingsService.get(db, organisation_id)
