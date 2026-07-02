"""TimetableService — CRUD weekly slots for a class + a "today" view. Org-scoped and
capability-driven: a slot's instructor must be an instructor/class_head-capable member,
and a slot's subject must be attached to the class.
"""
from __future__ import annotations
from datetime import time as time_cls

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.timetable import TimetableSlot


def _hhmm(t) -> str | None:
    return t.strftime("%H:%M") if t else None


class TimetableService:
    @staticmethod
    async def _belongs(db, organisation_id, table: str, _id) -> bool:
        from ...class_management.services.class_service import ClassService
        return await ClassService._belongs(db, organisation_id, table, _id)

    @staticmethod
    async def _validate_instructor(db, organisation_id, instructor_member_id):
        if not instructor_member_id:
            return None
        from ...class_management.services.class_service import ClassService
        if not await ClassService._member_active(db, organisation_id, instructor_member_id):
            raise ValueError("That instructor is not an active member of this organisation.")
        from ...auth_rbac.access import capabilities as cap
        caps = await ClassService._member_capabilities(db, organisation_id, instructor_member_id)
        if not (cap.has_capability(caps, "instructor") or cap.has_capability(caps, "class_head")):
            raise ValueError("The selected instructor's role cannot teach.")
        return instructor_member_id

    @staticmethod
    async def _validate(db, *, organisation_id, class_id, subject_id, instructor_member_id,
                        weekday, start_time, end_time):
        if not await TimetableService._belongs(db, organisation_id, "classes", class_id):
            raise ValueError("Invalid class for this organisation.")
        if weekday is None or int(weekday) < 0 or int(weekday) > 6:
            raise ValueError("Weekday must be 0 (Mon) … 6 (Sun).")
        if not start_time or not end_time or start_time >= end_time:
            raise ValueError("End time must be after start time.")
        if subject_id:
            link = (await db.execute(text(
                "SELECT 1 FROM class_subjects WHERE class_id = :c AND subject_id = :s "
                "AND organisation_id = :o AND is_deleted = false LIMIT 1"),
                {"c": str(class_id), "s": str(subject_id), "o": str(organisation_id)})).first()
            if not link:
                raise ValueError("Attach the subject to the class before scheduling it.")
        return await TimetableService._validate_instructor(db, organisation_id, instructor_member_id)

    @staticmethod
    def _serialize(s: TimetableSlot) -> dict:
        return {
            "id": str(s.id), "class_id": str(s.class_id),
            "subject_id": str(s.subject_id) if s.subject_id else None,
            "instructor_member_id": str(s.instructor_member_id) if s.instructor_member_id else None,
            "weekday": s.weekday,
            "start_time": _hhmm(s.start_time), "end_time": _hhmm(s.end_time),
            "room": s.room,
        }

    @staticmethod
    async def create(db: AsyncSession, *, organisation_id, class_id, weekday, start_time,
                     end_time, subject_id=None, instructor_member_id=None, room=None) -> TimetableSlot:
        instructor_member_id = await TimetableService._validate(
            db, organisation_id=organisation_id, class_id=class_id, subject_id=subject_id,
            instructor_member_id=instructor_member_id, weekday=weekday,
            start_time=start_time, end_time=end_time)
        from sqlalchemy.exc import IntegrityError
        slot = TimetableSlot(
            organisation_id=organisation_id, class_id=class_id, subject_id=subject_id or None,
            instructor_member_id=instructor_member_id, weekday=int(weekday),
            start_time=start_time, end_time=end_time, room=(room or None))
        db.add(slot)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ValueError("A slot already exists at that day and time for this class and subject.")
        await db.refresh(slot)
        return slot

    @staticmethod
    async def get(db, organisation_id, slot_id):
        return (await db.execute(
            select(TimetableSlot).where(
                TimetableSlot.id == slot_id,
                TimetableSlot.organisation_id == organisation_id,
                TimetableSlot.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()

    @staticmethod
    async def update(db: AsyncSession, slot: TimetableSlot, *, weekday=None, start_time=None,
                     end_time=None, subject_id=..., instructor_member_id=..., room=...) -> TimetableSlot:
        new_weekday = slot.weekday if weekday is None else int(weekday)
        new_start = slot.start_time if start_time is None else start_time
        new_end = slot.end_time if end_time is None else end_time
        new_subject = slot.subject_id if subject_id is ... else (subject_id or None)
        new_instructor = slot.instructor_member_id if instructor_member_id is ... else (instructor_member_id or None)
        validated_instructor = await TimetableService._validate(
            db, organisation_id=slot.organisation_id, class_id=slot.class_id,
            subject_id=new_subject, instructor_member_id=new_instructor,
            weekday=new_weekday, start_time=new_start, end_time=new_end)
        slot.weekday = new_weekday
        slot.start_time = new_start
        slot.end_time = new_end
        slot.subject_id = new_subject
        slot.instructor_member_id = validated_instructor
        if room is not ...:
            slot.room = room or None
        from sqlalchemy.exc import IntegrityError
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ValueError("A slot already exists at that day and time for this class and subject.")
        await db.refresh(slot)
        return slot

    @staticmethod
    async def soft_delete(db: AsyncSession, slot: TimetableSlot) -> None:
        slot.is_deleted = True
        await db.commit()

    @staticmethod
    async def list_by_class(db: AsyncSession, organisation_id, class_id) -> list[dict]:
        """All slots for a class (with subject + instructor names), ordered day then time."""
        rows = (await db.execute(text(
            """
            SELECT ts.id, ts.weekday, ts.start_time, ts.end_time, ts.room,
                   ts.subject_id, sub.name AS subject_name,
                   ts.instructor_member_id, m.first_name, m.last_name
            FROM timetable_slots ts
            LEFT JOIN subjects sub ON sub.id = ts.subject_id AND sub.is_deleted = false
            LEFT JOIN members m ON m.id = ts.instructor_member_id AND m.is_deleted = false
            WHERE ts.class_id = :c AND ts.organisation_id = :o AND ts.is_deleted = false
            ORDER BY ts.weekday, ts.start_time
            """), {"c": str(class_id), "o": str(organisation_id)})).all()
        return [TimetableService._row(r) for r in rows]

    @staticmethod
    async def today(db: AsyncSession, organisation_id, weekday: int,
                    instructor_member_id=None) -> list[dict]:
        """Every slot on a weekday across the org (optionally only a given instructor's) —
        powers a 'today's classes' view. Includes the class name."""
        params = {"o": str(organisation_id), "w": int(weekday)}
        extra = ""
        if instructor_member_id:
            extra = "AND ts.instructor_member_id = :im "
            params["im"] = str(instructor_member_id)
        rows = (await db.execute(text(
            f"""
            SELECT ts.id, ts.weekday, ts.start_time, ts.end_time, ts.room,
                   ts.subject_id, sub.name AS subject_name,
                   ts.instructor_member_id, m.first_name, m.last_name,
                   ts.class_id, c.name AS class_name
            FROM timetable_slots ts
            JOIN classes c ON c.id = ts.class_id AND c.is_deleted = false
            LEFT JOIN subjects sub ON sub.id = ts.subject_id AND sub.is_deleted = false
            LEFT JOIN members m ON m.id = ts.instructor_member_id AND m.is_deleted = false
            WHERE ts.organisation_id = :o AND ts.weekday = :w AND ts.is_deleted = false {extra}
            ORDER BY ts.start_time
            """), params)).all()
        out = []
        for r in rows:
            d = TimetableService._row(r)
            d["class_id"] = str(r[10])
            d["class_name"] = r[11]
            out.append(d)
        return out

    @staticmethod
    def _row(r) -> dict:
        instr = f"{r[8] or ''} {r[9] or ''}".strip()
        return {
            "id": str(r[0]), "weekday": r[1],
            "start_time": _hhmm(r[2]), "end_time": _hhmm(r[3]), "room": r[4],
            "subject_id": str(r[5]) if r[5] else None, "subject_name": r[6],
            "instructor_member_id": str(r[7]) if r[7] else None,
            "instructor_name": instr or None,
        }
