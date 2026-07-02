"""ClassSubjectService — link subjects to a class and assign instructors to a
(class, subject), all org-scoped. An instructor assignment is gated on the member's
role carrying the 'instructor' CAPABILITY — never a hardcoded teacher role.

Reserved for Phase-1 timetable/attendance; the endpoints exist now so the schema and
rules are settled. See important_documents/CONNECTIONS_AND_FLOW.md §3.3.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.class_subject import ClassSubject, SubjectTeacher
from .class_service import ClassService


class ClassSubjectService:
    # --------------------------- class ↔ subject ---------------------------
    @staticmethod
    async def list_class_subjects(db: AsyncSession, organisation_id, class_id) -> list[dict]:
        rows = (await db.execute(text(
            """
            SELECT cs.id, cs.subject_id, s.name, s.code
            FROM class_subjects cs JOIN subjects s ON s.id = cs.subject_id
            WHERE cs.class_id = :c AND cs.organisation_id = :o
              AND cs.is_deleted = false AND s.is_deleted = false
            ORDER BY s.name
            """), {"c": str(class_id), "o": str(organisation_id)})).all()
        return [{"id": str(r[0]), "subject_id": str(r[1]), "name": r[2], "code": r[3]}
                for r in rows]

    @staticmethod
    async def link_subject(db: AsyncSession, *, organisation_id, class_id, subject_id) -> dict:
        if not await ClassService._belongs(db, organisation_id, "classes", class_id):
            raise ValueError("Invalid class for this organisation.")
        if not await ClassService._belongs(db, organisation_id, "subjects", subject_id):
            raise ValueError("Invalid subject for this organisation.")
        dup = (await db.execute(text(
            "SELECT 1 FROM class_subjects WHERE class_id = :c AND subject_id = :s "
            "AND is_deleted = false LIMIT 1"),
            {"c": str(class_id), "s": str(subject_id)})).first()
        if dup:
            raise ValueError("This subject is already attached to the class.")
        row = ClassSubject(organisation_id=organisation_id, class_id=class_id, subject_id=subject_id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return {"id": str(row.id), "subject_id": str(subject_id)}

    @staticmethod
    async def unlink_subject(db: AsyncSession, organisation_id, class_id, cs_id) -> None:
        row = (await db.execute(
            select(ClassSubject).where(
                ClassSubject.id == cs_id,
                ClassSubject.class_id == class_id,
                ClassSubject.organisation_id == organisation_id,
                ClassSubject.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if not row:
            raise ValueError("Subject link not found.")
        row.is_deleted = True
        # Drop any instructor assignments for this (class, subject) too.
        await db.execute(text(
            "UPDATE subject_teachers SET is_deleted = true "
            "WHERE class_id = :c AND subject_id = :s AND is_deleted = false"),
            {"c": str(class_id), "s": str(row.subject_id)})
        await db.commit()

    # ------------------------ subject ↔ instructor ------------------------
    @staticmethod
    async def list_teachers(db: AsyncSession, organisation_id, class_id, subject_id) -> list[dict]:
        rows = (await db.execute(text(
            """
            SELECT st.id, st.member_id, m.first_name, m.last_name, r.role_name
            FROM subject_teachers st JOIN members m ON m.id = st.member_id
            LEFT JOIN rbac_roles r ON r.id = m.rbac_role_id
            WHERE st.class_id = :c AND st.subject_id = :s AND st.organisation_id = :o
              AND st.is_deleted = false AND m.is_deleted = false
            ORDER BY m.first_name
            """), {"c": str(class_id), "s": str(subject_id), "o": str(organisation_id)})).all()
        return [{"id": str(r[0]), "member_id": str(r[1]),
                 "name": f"{r[2]} {r[3]}".strip(), "role_name": r[4]} for r in rows]

    @staticmethod
    async def assign_teacher(db: AsyncSession, *, organisation_id, class_id, subject_id,
                             member_id) -> dict:
        if not await ClassService._belongs(db, organisation_id, "members", member_id):
            raise ValueError("That member does not belong to this organisation.")
        # The subject must be attached to the class first.
        link = (await db.execute(text(
            "SELECT 1 FROM class_subjects WHERE class_id = :c AND subject_id = :s "
            "AND organisation_id = :o AND is_deleted = false LIMIT 1"),
            {"c": str(class_id), "s": str(subject_id), "o": str(organisation_id)})).first()
        if not link:
            raise ValueError("Attach the subject to the class before assigning an instructor.")
        # Capability gate: only a member whose ROLE can teach may instruct a subject.
        from ...auth_rbac.access import capabilities as cap
        caps = await ClassService._member_capabilities(db, organisation_id, member_id)
        if not cap.has_capability(caps, "instructor"):
            raise ValueError("That member's role cannot teach (no instructor capability).")
        dup = (await db.execute(text(
            "SELECT 1 FROM subject_teachers WHERE class_id = :c AND subject_id = :s "
            "AND member_id = :m AND is_deleted = false LIMIT 1"),
            {"c": str(class_id), "s": str(subject_id), "m": str(member_id)})).first()
        if dup:
            raise ValueError("This member already teaches that subject in this class.")
        row = SubjectTeacher(organisation_id=organisation_id, class_id=class_id,
                             subject_id=subject_id, member_id=member_id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return {"id": str(row.id), "member_id": str(member_id)}

    @staticmethod
    async def unassign_teacher(db: AsyncSession, organisation_id, class_id, st_id) -> None:
        row = (await db.execute(
            select(SubjectTeacher).where(
                SubjectTeacher.id == st_id,
                SubjectTeacher.class_id == class_id,
                SubjectTeacher.organisation_id == organisation_id,
                SubjectTeacher.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if not row:
            raise ValueError("Instructor assignment not found.")
        row.is_deleted = True
        await db.commit()
