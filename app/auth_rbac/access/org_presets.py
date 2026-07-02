"""Org-type STARTER ROLE presets — seeded on org creation so a new org is immediately
usable (it has roles to assign, each with its capabilities already wired) and the
"first login needs a default role" gap is closed.

org_type only sets DEFAULTS here — never a runtime branch. Everything seeded is fully
editable/deletable in Roles & Access. The named org head is attached to the head role.
The `default` role (a no-access learner) is the SAFE fallback auto-assigned to a roleless
member at first-login, so a misconfigured account can sign in but sees nothing until an
admin gives it a real role — fail-closed, never a hard lockout.

See important_documents/CONNECTIONS_AND_FLOW.md §8.
"""
from __future__ import annotations

_DEFAULT_KEY = "_default"

# Per org_type: ordered starter roles. Each entry:
#   name    — role name (admin renames freely)
#   caps    — capability keys from access/capabilities.py
#   default — auto-assign to a roleless new member (pick the safe no-access learner)
#   head    — assign the org's named head to this role
STARTER_ROLES: dict[str, list[dict]] = {
    "school": [
        {"name": "Principal", "caps": ["admin_staff", "class_head"], "head": True},
        {"name": "Teacher", "caps": ["instructor", "class_head"]},
        {"name": "Student", "caps": ["learner"], "default": True},
        {"name": "Parent", "caps": ["guardian"]},
    ],
    "college": [
        {"name": "Director", "caps": ["admin_staff"], "head": True},
        {"name": "Professor", "caps": ["instructor"]},
        {"name": "Student", "caps": ["learner"], "default": True},
    ],
    "university": [
        {"name": "Director", "caps": ["admin_staff"], "head": True},
        {"name": "Professor", "caps": ["instructor"]},
        {"name": "Student", "caps": ["learner"], "default": True},
    ],
    "coaching": [
        {"name": "Director", "caps": ["admin_staff"], "head": True},
        {"name": "Coach", "caps": ["instructor"]},
        {"name": "Student", "caps": ["learner"], "default": True},
    ],
    "institute": [
        {"name": "Director", "caps": ["admin_staff"], "head": True},
        {"name": "Instructor", "caps": ["instructor"]},
        {"name": "Student", "caps": ["learner"], "default": True},
    ],
    # A private tutor IS the admin — no head role; just the people they teach.
    "tutor": [
        {"name": "Student", "caps": ["learner"], "default": True},
        {"name": "Parent", "caps": ["guardian"]},
    ],
    _DEFAULT_KEY: [
        {"name": "Head", "caps": ["admin_staff"], "head": True},
        {"name": "Member", "caps": ["learner"], "default": True},
    ],
}


def starter_roles_for(org_type: str) -> list[dict]:
    return STARTER_ROLES.get((org_type or "").strip().lower(), STARTER_ROLES[_DEFAULT_KEY])


async def seed_starter_roles(db, *, organisation_id, org_type, created_by=None,
                             head_name=None) -> dict:
    """Idempotent org-setup seeding. If the org has NO roles yet, create its org_type's
    starter roles (capabilities + a safe default) and, when a head name is given, attach
    that person to the head role as a name-only invited member. Safe to call from any
    org-create path; a second call (or the other path) no-ops. Never raises into the
    caller — best-effort, an org must be created even if seeding hiccups."""
    from sqlalchemy import select, func
    from .models import RbacRole
    from .service import RBACService
    from ...staff_management.models.member import Member

    existing = (await db.execute(
        select(func.count()).select_from(RbacRole).where(
            RbacRole.organisation_id == organisation_id,
            RbacRole.is_deleted == False,  # noqa: E712
        ))).scalar()
    if existing and int(existing) > 0:
        return {"seeded": 0, "skipped": "roles already exist"}

    presets = starter_roles_for(org_type)
    created: dict[str, object] = {}
    head_role_name = None
    for p in presets:
        role = await RBACService.create_role(
            db, organisation_id=organisation_id, user_type="staff", role_name=p["name"],
            description="Starter role (created on org setup — edit freely).",
            is_default=bool(p.get("default")),
            created_by=str(created_by) if created_by else None,
            capabilities=p.get("caps") or [],
        )
        created[p["name"]] = role
        if p.get("head"):
            head_role_name = p["name"]

    head = None
    head_name = (head_name or "").strip()
    if head_name and head_role_name:
        parts = head_name.split()
        member = Member(
            organisation_id=organisation_id, rbac_role_id=created[head_role_name].id,
            first_name=parts[0], last_name=" ".join(parts[1:]) if len(parts) > 1 else "",
            phone=None, status="invited", role="staff", created_by=created_by,
        )
        db.add(member)
        await db.commit()
        head = {"role": head_role_name, "member": head_name}

    return {"seeded": len(created), "roles": list(created.keys()), "head": head}
