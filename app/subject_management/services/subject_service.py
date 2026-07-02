"""SubjectService — simple org-scoped CRUD for subjects."""
from __future__ import annotations
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.subject import Subject


class SubjectService:
    @staticmethod
    def _serialize(s: Subject) -> dict:
        return {"id": str(s.id), "name": s.name, "code": s.code,
                "created_at": s.created_at.isoformat() if s.created_at else None}

    @staticmethod
    async def list(db: AsyncSession, organisation_id) -> list[dict]:
        rows = (await db.execute(
            select(Subject)
            .where(Subject.organisation_id == organisation_id,
                   Subject.is_deleted == False)  # noqa: E712
            .order_by(Subject.name)
            .limit(1000)  # safety cap against an unbounded fetch
        )).scalars().all()
        return [SubjectService._serialize(s) for s in rows]

    @staticmethod
    async def get(db: AsyncSession, organisation_id, subject_id) -> Optional[Subject]:
        return (await db.execute(
            select(Subject).where(
                Subject.id == subject_id,
                Subject.organisation_id == organisation_id,
                Subject.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, *, organisation_id, name, code=None) -> Subject:
        name = (name or "").strip()
        if not name:
            raise ValueError("Subject name is required.")
        s = Subject(organisation_id=organisation_id, name=name, code=(code or None))
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s

    @staticmethod
    async def update(db: AsyncSession, s: Subject, *, name=None, code=None) -> Subject:
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Subject name is required.")
            s.name = name
        if code is not None:
            s.code = code or None
        await db.commit()
        await db.refresh(s)
        return s

    @staticmethod
    async def soft_delete(db: AsyncSession, s: Subject) -> None:
        s.is_deleted = True
        await db.commit()
