"""ClassService — org-scoped CRUD for classes (the generic Class/Batch/Course container,
a self-referencing tree) + membership (members joined with an in-class role).

Tenant isolation: every referenced id (session, parent class, member) is verified to
belong to the caller's organisation before it is stored — no cross-org references and no
enumeration oracle.
"""
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.class_group import ClassGroup, ClassMembership


class ClassService:
    @staticmethod
    def _serialize(c: ClassGroup, *, member_count: int = 0) -> dict:
        return {
            "id": str(c.id),
            "name": c.name,
            "kind_label": c.kind_label,
            "parent_id": str(c.parent_id) if c.parent_id else None,
            "session_id": str(c.session_id) if c.session_id else None,
            "member_count": member_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }

    @staticmethod
    async def list(db: AsyncSession, organisation_id, *, session_id=None) -> list[dict]:
        stmt = select(ClassGroup).where(ClassGroup.organisation_id == organisation_id,
                                        ClassGroup.is_deleted == False)  # noqa: E712
        if session_id:
            stmt = stmt.where(ClassGroup.session_id == session_id)
        # Safety cap so a pathological org can't force an unbounded fetch. Realistic orgs
        # are well under this; a paginated "load more" UI comes when a module needs it.
        rows = (await db.execute(stmt.order_by(ClassGroup.name).limit(1000))).scalars().all()
        counts: dict[str, int] = {}
        if rows:
            cres = (await db.execute(
                select(ClassMembership.class_id, func.count())
                .where(ClassMembership.class_id.in_([c.id for c in rows]),
                       ClassMembership.is_deleted == False)  # noqa: E712
                .group_by(ClassMembership.class_id)
            )).all()
            counts = {str(cid): int(n) for cid, n in cres}
        return [ClassService._serialize(c, member_count=counts.get(str(c.id), 0)) for c in rows]

    @staticmethod
    async def get(db: AsyncSession, organisation_id, class_id) -> Optional[ClassGroup]:
        return (await db.execute(
            select(ClassGroup).where(ClassGroup.id == class_id,
                                     ClassGroup.organisation_id == organisation_id,
                                     ClassGroup.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()

    @staticmethod
    async def _belongs(db: AsyncSession, organisation_id, table: str, _id) -> bool:
        """Org-scoped existence check for a referenced id (table is a fixed internal
        literal, never user input)."""
        row = (await db.execute(
            text(f"SELECT 1 FROM {table} WHERE id = :id AND organisation_id = :org "
                 "AND is_deleted = false LIMIT 1"),
            {"id": str(_id), "org": str(organisation_id)},
        )).first()
        return bool(row)

    @staticmethod
    async def create(db: AsyncSession, *, organisation_id, name, kind_label=None,
                     session_id=None, parent_id=None) -> ClassGroup:
        name = (name or "").strip()
        if not name:
            raise ValueError("Class name is required.")
        if session_id and not await ClassService._belongs(db, organisation_id, "academic_sessions", session_id):
            raise ValueError("Invalid session for this organisation.")
        if parent_id and not await ClassService._belongs(db, organisation_id, "classes", parent_id):
            raise ValueError("Invalid parent class for this organisation.")
        c = ClassGroup(organisation_id=organisation_id, name=name, kind_label=(kind_label or None),
                       session_id=(session_id or None), parent_id=(parent_id or None))
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c

    @staticmethod
    async def update(db: AsyncSession, c: ClassGroup, *, name=None, kind_label=None,
                     session_id=None, parent_id=None) -> ClassGroup:
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Class name is required.")
            c.name = name
        if kind_label is not None:
            c.kind_label = kind_label or None
        if session_id is not None:
            if session_id and not await ClassService._belongs(db, c.organisation_id, "academic_sessions", session_id):
                raise ValueError("Invalid session for this organisation.")
            c.session_id = session_id or None
        if parent_id is not None:
            if parent_id:
                if str(parent_id) == str(c.id):
                    raise ValueError("A class cannot be its own parent.")
                if not await ClassService._belongs(db, c.organisation_id, "classes", parent_id):
                    raise ValueError("Invalid parent class for this organisation.")
            c.parent_id = parent_id or None
        await db.commit()
        await db.refresh(c)
        return c

    @staticmethod
    async def soft_delete(db: AsyncSession, c: ClassGroup) -> None:
        c.is_deleted = True
        await db.commit()

    # ----------------------------- membership -----------------------------
    @staticmethod
    async def list_members(db: AsyncSession, organisation_id, class_id) -> list[dict]:
        rows = (await db.execute(text(
            """
            SELECT cm.id, cm.member_id, cm.capacity, m.first_name, m.last_name, m.staff_id,
                   r.role_name
            FROM class_members cm JOIN members m ON m.id = cm.member_id
            LEFT JOIN rbac_roles r ON r.id = m.rbac_role_id
            WHERE cm.class_id = :cid AND cm.organisation_id = :org
              AND cm.is_deleted = false AND m.is_deleted = false
            ORDER BY cm.capacity NULLS LAST, m.first_name
            """), {"cid": str(class_id), "org": str(organisation_id)})).all()
        return [{"id": str(r[0]), "member_id": str(r[1]), "capacity": r[2],
                 "name": f"{r[3]} {r[4]}".strip(), "staff_id": r[5], "role_name": r[6]}
                for r in rows]

    @staticmethod
    async def _member_capabilities(db: AsyncSession, organisation_id, member_id) -> list[str]:
        """The capability keys of a member's dynamic role ([] if none)."""
        rid = (await db.execute(text(
            "SELECT rbac_role_id FROM members WHERE id = :m AND organisation_id = :org "
            "AND is_deleted = false"),
            {"m": str(member_id), "org": str(organisation_id)})).scalar()
        if not rid:
            return []
        from ...auth_rbac.access.service import RBACService
        return await RBACService.role_capabilities(db, rid)

    @staticmethod
    async def _member_active(db: AsyncSession, organisation_id, member_id) -> bool:
        """True iff the member is a live, ACTIVE account (not deactivated). Used to keep a
        deactivated member from being assigned as an instructor."""
        row = (await db.execute(text(
            "SELECT 1 FROM members WHERE id = :m AND organisation_id = :o "
            "AND is_deleted = false AND status = 'active' LIMIT 1"),
            {"m": str(member_id), "o": str(organisation_id)})).first()
        return bool(row)

    @staticmethod
    async def add_member(db: AsyncSession, *, organisation_id, class_id, member_id,
                         capacity=None) -> dict:
        # Defense-in-depth: validate the class independently of the router's _load() so a
        # direct/background call can never link a member into a cross-org or deleted class.
        if not await ClassService._belongs(db, organisation_id, "classes", class_id):
            raise ValueError("Invalid class for this organisation.")
        if not await ClassService._belongs(db, organisation_id, "members", member_id):
            raise ValueError("That member does not belong to this organisation.")
        # Capacity is a PARTICIPANT capability of the member's role — never a hardcoded
        # student/teacher/assistant. If given, it must be one the member's role actually
        # has; if omitted, derive it (single → that one, several → the primary, none → NULL).
        from ...auth_rbac.access import capabilities as cap
        participant = cap.participant_capabilities(
            await ClassService._member_capabilities(db, organisation_id, member_id))
        if capacity:
            capacity = str(capacity).strip().lower()
            if capacity not in cap.PARTICIPANT_CAPABILITIES:
                raise ValueError("Invalid capacity.")
            if capacity not in participant:
                raise ValueError("That member's role cannot take that capacity.")
        else:
            capacity = participant[0] if participant else None
        # One membership per (class, member); their capacity comes from their role.
        dup = (await db.execute(text(
            "SELECT 1 FROM class_members WHERE class_id = :c AND member_id = :m "
            "AND is_deleted = false LIMIT 1"),
            {"c": str(class_id), "m": str(member_id)})).first()
        if dup:
            raise ValueError("This member is already in the class.")
        cm = ClassMembership(organisation_id=organisation_id, class_id=class_id,
                             member_id=member_id, capacity=capacity)
        db.add(cm)
        await db.commit()
        await db.refresh(cm)
        return {"id": str(cm.id), "member_id": str(member_id), "capacity": capacity}

    @staticmethod
    async def remove_member(db: AsyncSession, organisation_id, class_id, cm_id) -> None:
        row = (await db.execute(
            select(ClassMembership).where(
                ClassMembership.id == cm_id,
                ClassMembership.class_id == class_id,
                ClassMembership.organisation_id == organisation_id,
                ClassMembership.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if not row:
            raise ValueError("Membership not found.")
        row.is_deleted = True
        await db.commit()
