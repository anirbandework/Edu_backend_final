"""AttendanceService — open (find-or-create) a class session and record its learners'
attendance. Everything is org-scoped and capability-driven: the roster is the class's
LEARNER-capacity members, and a named instructor must be instructor/class_head-capable.

See important_documents/MODULE_MASTER_PLAN.md §4.1.
"""
from __future__ import annotations

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.attendance import ClassSession, AttendanceRecord

STATUSES = {"present", "absent", "late", "excused", "leave"}
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


class AttendanceService:
    # ----------------------------- helpers -----------------------------
    @staticmethod
    async def _belongs(db, organisation_id, table: str, _id) -> bool:
        from ...class_management.services.class_service import ClassService
        return await ClassService._belongs(db, organisation_id, table, _id)

    @staticmethod
    def _serialize(s: ClassSession) -> dict:
        return {
            "id": str(s.id),
            "class_id": str(s.class_id),
            "subject_id": str(s.subject_id) if s.subject_id else None,
            "academic_session_id": str(s.academic_session_id) if s.academic_session_id else None,
            "instructor_member_id": str(s.instructor_member_id) if s.instructor_member_id else None,
            "date": s.date.isoformat() if s.date else None,
            "locked": bool(s.locked),
        }

    @staticmethod
    async def learner_roster(db: AsyncSession, organisation_id, class_id) -> list[dict]:
        """The class's LEARNER-capacity members — the people attendance is taken for.
        Capability-driven (capacity='learner'), never a hardcoded 'student'."""
        rows = (await db.execute(text(
            """
            SELECT cm.member_id, m.first_name, m.last_name, m.staff_id, r.role_name
            FROM class_members cm
            JOIN members m ON m.id = cm.member_id
            LEFT JOIN rbac_roles r ON r.id = m.rbac_role_id
            WHERE cm.class_id = :c AND cm.organisation_id = :o
              AND cm.is_deleted = false AND m.is_deleted = false
              AND cm.capacity = 'learner'
            ORDER BY m.first_name, m.last_name
            """), {"c": str(class_id), "o": str(organisation_id)})).all()
        return [{"member_id": str(r[0]), "name": f"{r[1]} {r[2]}".strip(),
                 "staff_id": r[3], "role_name": r[4]} for r in rows]

    @staticmethod
    async def _current_academic_session(db, organisation_id):
        return (await db.execute(text(
            "SELECT id FROM academic_sessions WHERE organisation_id = :o "
            "AND is_current = true AND is_deleted = false LIMIT 1"),
            {"o": str(organisation_id)})).scalar()

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

    # ----------------------------- sessions -----------------------------
    @staticmethod
    async def get_or_create_session(db: AsyncSession, *, organisation_id, class_id, on_date,
                                    subject_id=None, instructor_member_id=None) -> ClassSession:
        if not await AttendanceService._belongs(db, organisation_id, "classes", class_id):
            raise ValueError("Invalid class for this organisation.")
        if subject_id:
            link = (await db.execute(text(
                "SELECT 1 FROM class_subjects WHERE class_id = :c AND subject_id = :s "
                "AND organisation_id = :o AND is_deleted = false LIMIT 1"),
                {"c": str(class_id), "s": str(subject_id), "o": str(organisation_id)})).first()
            if not link:
                raise ValueError("Attach the subject to the class before taking its attendance.")
        instructor_member_id = await AttendanceService._validate_instructor(
            db, organisation_id, instructor_member_id)

        existing_id = await AttendanceService._find_session_id(db, class_id, on_date, subject_id)
        if existing_id:
            return await AttendanceService._stamp_instructor(
                db, organisation_id, existing_id, instructor_member_id)

        from sqlalchemy.exc import IntegrityError
        acad = await AttendanceService._current_academic_session(db, organisation_id)
        sess = ClassSession(
            organisation_id=organisation_id, class_id=class_id, subject_id=subject_id or None,
            academic_session_id=acad, instructor_member_id=instructor_member_id, date=on_date)
        db.add(sess)
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent open() created the same (class, date, subject) first (the
            # uq_class_session_active index caught us) — return that existing session
            # instead of surfacing a 500. Find-or-create must be concurrency-safe.
            await db.rollback()
            existing_id = await AttendanceService._find_session_id(db, class_id, on_date, subject_id)
            if existing_id:
                return await AttendanceService._stamp_instructor(
                    db, organisation_id, existing_id, instructor_member_id)
            raise
        await db.refresh(sess)
        return sess

    @staticmethod
    async def _find_session_id(db, class_id, on_date, subject_id):
        """The live session id for (class, date, subject) — COALESCE mirrors the unique
        index so the daily case (subject NULL) collapses to one-per (class, date)."""
        return (await db.execute(text(
            "SELECT id FROM class_sessions WHERE class_id = :c AND date = :d "
            "AND COALESCE(subject_id, CAST(:nil AS uuid)) "
            "  = COALESCE(CAST(:s AS uuid), CAST(:nil AS uuid)) "
            "AND is_deleted = false LIMIT 1"),
            {"c": str(class_id), "d": on_date,
             "s": str(subject_id) if subject_id else None, "nil": _NIL_UUID})).scalar()

    @staticmethod
    async def _stamp_instructor(db, organisation_id, session_id, instructor_member_id):
        sess = await AttendanceService.get_session(db, organisation_id, session_id)
        if instructor_member_id and sess is not None and not sess.instructor_member_id:
            sess.instructor_member_id = instructor_member_id
            await db.commit()
            await db.refresh(sess)
        return sess

    @staticmethod
    async def get_session(db, organisation_id, session_id):
        return (await db.execute(
            select(ClassSession).where(
                ClassSession.id == session_id,
                ClassSession.organisation_id == organisation_id,
                ClassSession.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()

    @staticmethod
    async def _records_map(db, session_id) -> dict:
        rows = (await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.class_session_id == session_id,
                AttendanceRecord.is_deleted == False)  # noqa: E712
        )).scalars().all()
        return {str(r.member_id): r.status for r in rows}

    @staticmethod
    async def open(db: AsyncSession, *, organisation_id, class_id, on_date, subject_id=None,
                   instructor_member_id=None) -> dict:
        """The one call the marking screen needs: find-or-create the session, plus the
        learner roster and any already-saved statuses (so unmarked learners default to
        present in the UI)."""
        sess = await AttendanceService.get_or_create_session(
            db, organisation_id=organisation_id, class_id=class_id, on_date=on_date,
            subject_id=subject_id, instructor_member_id=instructor_member_id)
        roster = await AttendanceService.learner_roster(db, organisation_id, class_id)
        records = await AttendanceService._records_map(db, sess.id)
        return {"session": AttendanceService._serialize(sess), "roster": roster, "records": records}

    @staticmethod
    async def save(db: AsyncSession, *, organisation_id, session_id, records: list[dict],
                   marked_by=None, instructor_member_id=None) -> dict:
        sess = await AttendanceService.get_session(db, organisation_id, session_id)
        if not sess:
            raise ValueError("Attendance session not found.")
        if sess.locked:
            raise ValueError("This attendance is locked and cannot be changed.")
        if instructor_member_id:
            sess.instructor_member_id = await AttendanceService._validate_instructor(
                db, organisation_id, instructor_member_id)

        roster_ids = {r["member_id"] for r in
                      await AttendanceService.learner_roster(db, organisation_id, sess.class_id)}
        existing = {
            str(r.member_id): r for r in (await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.class_session_id == session_id,
                    AttendanceRecord.is_deleted == False)  # noqa: E712
            )).scalars().all()
        }
        saved = 0
        for item in (records or []):
            mid = str(item.get("member_id") or "")
            status = str(item.get("status") or "").strip().lower()
            if status not in STATUSES:
                raise ValueError(f"Invalid status '{status}'.")
            if mid not in roster_ids:
                continue  # only the class's learners can be marked
            row = existing.get(mid)
            if row:
                row.status = status
                row.marked_by = marked_by
                row.marked_at = func.now()
            else:
                db.add(AttendanceRecord(
                    organisation_id=organisation_id, class_session_id=session_id,
                    member_id=mid, status=status, marked_by=marked_by))
            saved += 1
        await db.commit()
        return {"session_id": str(session_id), "saved": saved}

    @staticmethod
    async def learner_summary(db: AsyncSession, organisation_id, class_id) -> dict:
        """Per-learner attendance % for a class (present / marked across all its sessions).
        Capability-driven roster (learners only)."""
        total_sessions = (await db.execute(text(
            "SELECT count(*) FROM class_sessions "
            "WHERE class_id = :c AND organisation_id = :o AND is_deleted = false"),
            {"c": str(class_id), "o": str(organisation_id)})).scalar() or 0
        rows = (await db.execute(text(
            """
            SELECT cm.member_id, m.first_name, m.last_name,
                   COUNT(ar.id) AS marked,
                   COUNT(ar.id) FILTER (WHERE ar.status = 'present') AS present
            FROM class_members cm
            JOIN members m ON m.id = cm.member_id
            LEFT JOIN class_sessions s
              ON s.class_id = cm.class_id AND s.organisation_id = :o AND s.is_deleted = false
            LEFT JOIN attendance_records ar
              ON ar.class_session_id = s.id AND ar.member_id = cm.member_id AND ar.is_deleted = false
            WHERE cm.class_id = :c AND cm.organisation_id = :o AND cm.is_deleted = false
              AND cm.capacity = 'learner' AND m.is_deleted = false
            GROUP BY cm.member_id, m.first_name, m.last_name
            ORDER BY m.first_name, m.last_name
            """), {"c": str(class_id), "o": str(organisation_id)})).all()
        learners = []
        for r in rows:
            marked = int(r[3] or 0)
            present = int(r[4] or 0)
            learners.append({
                "member_id": str(r[0]),
                "name": f"{r[1]} {r[2]}".strip(),
                "present": present,
                "marked": marked,
                "pct": round(present * 100.0 / marked, 1) if marked else None,
            })
        return {"total_sessions": int(total_sessions), "learners": learners}

    @staticmethod
    async def list_sessions(db: AsyncSession, organisation_id, class_id, limit: int = 60) -> list[dict]:
        """Recent sessions for a class with present/total tallies (attendance history)."""
        limit = max(1, min(int(limit or 60), 200))
        rows = (await db.execute(text(
            """
            SELECT s.id, s.date, s.subject_id, sub.name,
                   COUNT(ar.id) FILTER (WHERE ar.is_deleted = false) AS marked,
                   COUNT(ar.id) FILTER (WHERE ar.is_deleted = false AND ar.status = 'present') AS present
            FROM class_sessions s
            LEFT JOIN subjects sub ON sub.id = s.subject_id AND sub.is_deleted = false
            LEFT JOIN attendance_records ar ON ar.class_session_id = s.id
            WHERE s.class_id = :c AND s.organisation_id = :o AND s.is_deleted = false
            GROUP BY s.id, s.date, s.subject_id, sub.name
            ORDER BY s.date DESC
            LIMIT :lim
            """), {"c": str(class_id), "o": str(organisation_id), "lim": limit})).all()
        return [{
            "id": str(r[0]),
            "date": r[1].isoformat() if r[1] else None,
            "subject_id": str(r[2]) if r[2] else None,
            "subject_name": r[3],
            "marked": int(r[4] or 0),
            "present": int(r[5] or 0),
        } for r in rows]
