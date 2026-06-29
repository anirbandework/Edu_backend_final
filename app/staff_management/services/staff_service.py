"""StaffService — CRUD for the unified members table + delegation checks."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.member import Member
from ...auth_rbac.security.password import hash_password_async
from ...auth_rbac.access.service import RBACService
from ...auth_rbac.access.models import RbacRole


def _gen_staff_id() -> str:
    return "STF-" + uuid.uuid4().hex[:6].upper()


class StaffService:
    @staticmethod
    async def list_staff(db: AsyncSession, organisation_id, *, limit: int = 100,
                         offset: int = 0, q: str = "", role_id: Optional[str] = None) -> dict:
        """Paginated + searchable staff list for one organisation. Returns an envelope
        {items, total, limit, offset} so the client can page (a school's students are
        staff members, so this list can be large). `q` matches name (incl. full
        "First Last"), email, phone, staff id, OR role name; `role_id` filters to one role."""
        base = select(Member).where(Member.organisation_id == organisation_id)
        if hasattr(Member, "is_deleted"):
            base = base.where(Member.is_deleted == False)  # noqa: E712
        if role_id:
            base = base.where(Member.rbac_role_id == role_id)
        term = (q or "").strip()
        if term:
            like = f"%{term}%"
            # roles in THIS org whose name matches — so "teacher" finds everyone with that role.
            role_match = (
                select(RbacRole.id)
                .where(RbacRole.organisation_id == organisation_id,
                       RbacRole.role_name.ilike(like))
            )
            base = base.where(or_(
                Member.first_name.ilike(like),
                Member.last_name.ilike(like),
                # full name, so "John Doe" matches first+last together (concat is NULL-safe)
                func.concat(Member.first_name, " ", Member.last_name).ilike(like),
                Member.email.ilike(like),
                Member.phone.ilike(like),
                Member.staff_id.ilike(like),
                Member.rbac_role_id.in_(role_match),
            ))
        total = (await db.execute(
            select(func.count()).select_from(base.subquery())
        )).scalar() or 0
        rows = (await db.execute(
            base.order_by(Member.created_at.desc()).limit(limit).offset(offset)
        )).scalars().all()
        # role names in one shot
        role_ids = {str(s.rbac_role_id) for s in rows if s.rbac_role_id}
        role_names: dict[str, str] = {}
        if role_ids:
            rroles = (await db.execute(
                select(RbacRole).where(RbacRole.id.in_(list(role_ids)))
            )).scalars().all()
            role_names = {str(r.id): r.role_name for r in rroles}
        return {
            "items": [StaffService._serialize(s, role_names) for s in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def _serialize(s: Member, role_names: dict) -> dict:
        return {
            "id": str(s.id),
            "staff_id": s.staff_id,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "name": f"{s.first_name} {s.last_name}".strip(),
            "email": s.email,
            "phone": s.phone,
            "position": s.position,
            "status": s.status,
            "rbac_role_id": str(s.rbac_role_id) if s.rbac_role_id else None,
            "role_name": role_names.get(str(s.rbac_role_id)) if s.rbac_role_id else None,
            "has_login": bool(s.password_hash),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }

    @staticmethod
    async def get(db: AsyncSession, staff_id, organisation_id) -> Optional[Member]:
        stmt = select(Member).where(Member.id == staff_id, Member.organisation_id == organisation_id)
        if hasattr(Member, "is_deleted"):
            stmt = stmt.where(Member.is_deleted == False)  # noqa: E712
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _phone_taken(db: AsyncSession, phone: str, exclude_id=None) -> bool:
        """Phone must be unique across EVERY identity table — login resolves a user
        by phone across authorities + members, so a collision would let one account
        shadow another at login. (The legacy teachers/students tables were removed in
        the strip-down; the only identity tables now are members + authorities.)"""
        # members (allow excluding the row being updated)
        q = "SELECT 1 FROM members WHERE phone = :p AND is_deleted = false"
        params = {"p": phone}
        if exclude_id:
            q += " AND id <> :eid"
            params["eid"] = str(exclude_id)
        if (await db.execute(text(q + " LIMIT 1"), params)).first():
            return True
        row = (await db.execute(
            text("SELECT 1 FROM authorities WHERE phone = :p AND is_deleted = false LIMIT 1"),
            {"p": phone},
        )).first()
        return bool(row)

    @staticmethod
    async def create(
        db: AsyncSession, *, organisation_id, rbac_role_id, first_name, last_name, phone,
        password=None, email=None, position=None, created_by=None,
    ) -> Member:
        phone = (phone or "").strip()
        if not phone:
            raise ValueError("Phone number is required.")
        if await StaffService._phone_taken(db, phone):
            raise ValueError("A user with this phone number already exists.")
        # Password-less by design: the admin never sets a password. The user sets
        # their own at first login (phone + OTP); status='invited' until they do.
        staff = Member(
            organisation_id=organisation_id,
            rbac_role_id=rbac_role_id,
            staff_id=_gen_staff_id(),
            first_name=(first_name or "").strip(),
            last_name=(last_name or "").strip(),
            email=(email or None),
            phone=phone,
            password_hash=(await hash_password_async(password)) if password else None,
            position=(position or None),
            status="active" if password else "invited",
            role="staff",
            created_by=created_by,
        )
        db.add(staff)
        try:
            await db.commit()
        except IntegrityError:
            # Only `email` carries a DB unique constraint; phone is enforced above.
            await db.rollback()
            raise ValueError("That email is already in use.")
        await db.refresh(staff)
        return staff

    @staticmethod
    async def update(db: AsyncSession, staff: Member, *, first_name=None, last_name=None,
                     email=None, phone=None, position=None, rbac_role_id=None) -> Member:
        if phone is not None:
            phone = phone.strip()
            if phone and phone != staff.phone and await StaffService._phone_taken(db, phone, exclude_id=staff.id):
                raise ValueError("A staff member with this phone already exists.")
            staff.phone = phone or staff.phone
        if first_name is not None:
            staff.first_name = first_name.strip()
        if last_name is not None:
            staff.last_name = last_name.strip()
        if email is not None:
            staff.email = email or None
        if position is not None:
            staff.position = position or None
        if rbac_role_id is not None:
            staff.rbac_role_id = rbac_role_id or None
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ValueError("That email is already in use.")
        await db.refresh(staff)
        return staff

    @staticmethod
    async def set_status(db: AsyncSession, staff: Member, active: bool) -> Member:
        staff.status = "active" if active else "inactive"
        await db.commit()
        await db.refresh(staff)
        return staff

    @staticmethod
    async def reset_password(db: AsyncSession, staff: Member, new_password: str) -> None:
        if not new_password:
            raise ValueError("Password is required.")
        staff.password_hash = await hash_password_async(new_password)
        from ...auth_rbac.security.sessions import invalidate_sessions
        await invalidate_sessions(db, "staff", staff.id)  # log out the member's old sessions
        await db.commit()

    @staticmethod
    async def soft_delete(db: AsyncSession, staff: Member) -> None:
        if hasattr(staff, "is_deleted"):
            staff.is_deleted = True
        staff.status = "inactive"
        await db.commit()

    # ---- delegation ----
    @staticmethod
    async def can_principal_create_role(db: AsyncSession, principal, target_role_id) -> bool:
        """Admin/super-admin may assign any role in the organisation. A staff user who
        holds the "Staff & Users" page may assign any of the organisation's roles —
        granting that page IS the grant to manage users. (That the target is a staff
        role in this org is enforced by the caller in _validate_role.)"""
        if principal.is_super_admin or principal.is_authority:
            return True
        if principal.role != "staff":
            return False
        from ...auth_rbac.access.deps import resolve_role_id
        my_role = await resolve_role_id(db, "staff", principal.user_id)
        if not my_role:
            return False
        return await RBACService.has_module_access(
            db, user_type="staff", organisation_id=principal.organisation_uuid,
            role_id=my_role, module_key="staff",
        )
