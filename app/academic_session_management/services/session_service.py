"""SessionService — org-scoped CRUD for academic sessions. Exactly one session per
organisation may be `is_current`; setting one current clears the others."""
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.academic_session import AcademicSession


class SessionService:
    @staticmethod
    def _serialize(s: AcademicSession) -> dict:
        return {
            "id": str(s.id),
            "name": s.name,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "is_current": bool(s.is_current),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }

    @staticmethod
    async def list(db: AsyncSession, organisation_id) -> list[dict]:
        rows = (await db.execute(
            select(AcademicSession)
            .where(AcademicSession.organisation_id == organisation_id,
                   AcademicSession.is_deleted == False)  # noqa: E712
            .order_by(AcademicSession.is_current.desc(), AcademicSession.created_at.desc())
            .limit(1000)  # safety cap (sessions per org are realistically tiny)
        )).scalars().all()
        return [SessionService._serialize(s) for s in rows]

    @staticmethod
    async def get(db: AsyncSession, organisation_id, session_id) -> Optional[AcademicSession]:
        return (await db.execute(
            select(AcademicSession).where(
                AcademicSession.id == session_id,
                AcademicSession.organisation_id == organisation_id,
                AcademicSession.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()

    @staticmethod
    async def _clear_other_current(db: AsyncSession, organisation_id, keep_id) -> None:
        await db.execute(
            update(AcademicSession)
            .where(AcademicSession.organisation_id == organisation_id,
                   AcademicSession.id != keep_id,
                   AcademicSession.is_current == True)  # noqa: E712
            .values(is_current=False)
        )

    @staticmethod
    async def create(db: AsyncSession, *, organisation_id, name, start_date=None,
                     end_date=None, is_current=False) -> AcademicSession:
        name = (name or "").strip()
        if not name:
            raise ValueError("Session name is required.")
        if start_date and end_date and end_date < start_date:
            raise ValueError("End date cannot be before the start date.")
        s = AcademicSession(organisation_id=organisation_id, name=name,
                            start_date=start_date, end_date=end_date, is_current=bool(is_current))
        db.add(s)
        await db.flush()
        if is_current:
            await SessionService._clear_other_current(db, organisation_id, s.id)
        await db.commit()
        await db.refresh(s)
        return s

    @staticmethod
    async def update(db: AsyncSession, s: AcademicSession, *, name=None, start_date=None,
                     end_date=None, is_current=None) -> AcademicSession:
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Session name is required.")
            s.name = name
        if start_date is not None:
            s.start_date = start_date
        if end_date is not None:
            s.end_date = end_date
        if s.start_date and s.end_date and s.end_date < s.start_date:
            raise ValueError("End date cannot be before the start date.")
        if is_current is not None:
            s.is_current = bool(is_current)
            if s.is_current:
                await SessionService._clear_other_current(db, s.organisation_id, s.id)
        await db.commit()
        await db.refresh(s)
        return s

    @staticmethod
    async def soft_delete(db: AsyncSession, s: AcademicSession) -> None:
        s.is_deleted = True
        await db.commit()
