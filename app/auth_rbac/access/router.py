"""RBAC API: my-permissions (everyone), role management (authority), organisation config (super-admin)."""
from __future__ import annotations
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ..security.deps import get_current_principal, require_super_admin, require_authority
from ..security.principal import Principal
from . import catalog
from .service import RBACService
from .deps import resolve_role_id, _IDENTITY_TABLE

# NOTE: legacy /api/rbac is taken by the incoherent rbac_management router; this
# module/tab RBAC (the one we actually enforce) lives under /api/access.
router = APIRouter(prefix="/api/access", tags=["RBAC (module/tab)"])


# ---------- schemas ----------
class RoleCreate(BaseModel):
    role_name: str
    # Defaults to the unified dynamic-staff type: every admin-created role is
    # dynamic (the admin names it freely and picks its pages). Legacy
    # teacher/student/authority roles may still be created by passing user_type.
    user_type: str = "staff"
    description: Optional[str] = None
    is_default: bool = False
    modules: Optional[List[str]] = None              # cross-section page grants
    creatable_role_ids: Optional[List[str]] = None   # delegated user-creation


class RoleUpdate(BaseModel):
    role_name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    modules: Optional[List[str]] = None
    creatable_role_ids: Optional[List[str]] = None


class ModuleToggle(BaseModel):
    enabled: bool


def _actor(p: Principal) -> str:
    return f"{p.role}:{p.user_id}"


def _require_module(module_key: str):
    if catalog.get_module(module_key) is None:
        raise HTTPException(status_code=404, detail=f"Unknown module '{module_key}'")


def _require_tab(module_key: str, tab_key: str):
    _require_module(module_key)
    if tab_key not in catalog.tab_keys(module_key):
        raise HTTPException(status_code=404, detail=f"Unknown tab '{tab_key}' on '{module_key}'")


# ---------- catalog ----------
@router.get("/catalog")
async def get_catalog(principal: Principal = Depends(get_current_principal)):
    return {"modules": catalog.MODULES, "user_types": list(catalog.USER_TYPES)}


# ---------- my permissions (everyone) ----------
@router.get("/my-permissions")
async def my_permissions(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    # The ADMIN's OWN sidebar is now a super-admin-controlled ceiling ("Admin
    # pages"): only the admin-audience pages the super-admin left ON for this org
    # are shown. This is SEPARATE from the distributable org ceiling (what the
    # admin may hand to their users' roles). Required pages (Profile) stay on.
    if principal.role == "authority":
        modules = await RBACService.get_admin_permissions(db, principal.organisation_uuid)
        return {"user_type": principal.role, "modules": modules}
    if principal.is_super_admin:
        # super-admin sees the full catalog as "enabled"
        return {
            "user_type": "super_admin",
            "modules": [
                {"module_key": m["module_key"], "module_name": m["module_name"], "icon": m["icon"],
                 "path": m["path"], "enabled": True, "locked": False,
                 "tabs": [{"tab_key": t[0], "tab_label": t[1]} for t in m["tabs"]],
                 "tab_permissions": {t[0]: True for t in m["tabs"]}, "locked_tabs": {}}
                for m in catalog.MODULES
            ],
        }
    # Everyone else is a unified 'staff' user: pages come from their role's explicit
    # cross-section allow-list (default-DENY) ∩ the GROUP page-pool ceiling.
    role_id = await resolve_role_id(db, principal.role, principal.user_id)
    modules = await RBACService.get_staff_permissions(db, role_id, principal.organisation_uuid)
    return {"user_type": principal.role, "role_id": role_id, "modules": modules}


@router.get("/grantable-pages")
async def grantable_pages(principal: Principal = Depends(require_authority),
                          db: AsyncSession = Depends(get_db)):
    """For the admin's Roles & Access picker: every page + a `locked` flag (the org
    doesn't have it → show 'Premium / upgrade', not assignable)."""
    return await RBACService.grantable_pages(db, principal.organisation_uuid)


# ========= module-access ceilings (super-admin, PER INSTITUTION GROUP) =========
# Two ceilings, both applying to every organisation in the group:
#   (a) page pool  → /group/{id}/pages       (admins grant these to staff roles)
#   (b) admin pages → /group/{id}/admin-pages (what the admins themselves see)
def _valid_group(group_id: str) -> str:
    """Reject malformed group ids before they reach asyncpg (avoids a 500)."""
    try:
        import uuid as _uuid
        _uuid.UUID(str(group_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid group id")
    return group_id


@router.get("/group/{group_id}/pages")
async def group_pages(group_id: str, principal: Principal = Depends(require_super_admin),
                      db: AsyncSession = Depends(get_db)):
    """Ceiling (a): the page POOL a group may grant to roles ('what they paid for')."""
    return await RBACService.get_group_pages(db, _valid_group(group_id))


@router.put("/group/{group_id}/page/{module_key}")
async def set_group_page(group_id: str, module_key: str, body: ModuleToggle,
                         principal: Principal = Depends(require_super_admin),
                         db: AsyncSession = Depends(get_db)):
    _valid_group(group_id)
    try:
        await RBACService.set_group_page(db, group_id, module_key, body.enabled, by=_actor(principal))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"group_id": group_id, "module_key": module_key, "enabled": body.enabled}


@router.post("/group/{group_id}/pages/bulk")
async def set_group_pages_bulk(group_id: str, body: ModuleToggle,
                               principal: Principal = Depends(require_super_admin),
                               db: AsyncSession = Depends(get_db)):
    """Enable or revoke ALL (non-required) pool pages for a group at once."""
    _valid_group(group_id)
    await RBACService.set_all_group_pages(db, group_id, body.enabled, by=_actor(principal))
    return {"group_id": group_id, "enabled": body.enabled}


@router.get("/group/{group_id}/admin-pages")
async def group_admin_pages(group_id: str, principal: Principal = Depends(require_super_admin),
                            db: AsyncSession = Depends(get_db)):
    """Ceiling (b): which pages the group's ADMINS see in their own sidebar."""
    return await RBACService.get_admin_pages(db, _valid_group(group_id))


@router.put("/group/{group_id}/admin-page/{module_key}")
async def set_group_admin_page(group_id: str, module_key: str, body: ModuleToggle,
                               principal: Principal = Depends(require_super_admin),
                               db: AsyncSession = Depends(get_db)):
    _valid_group(group_id)
    try:
        await RBACService.set_admin_page(db, group_id, module_key, body.enabled, by=_actor(principal))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"group_id": group_id, "module_key": module_key, "enabled": body.enabled}


@router.post("/group/{group_id}/admin-pages/bulk")
async def set_group_admin_pages_bulk(group_id: str, body: ModuleToggle,
                                     principal: Principal = Depends(require_super_admin),
                                     db: AsyncSession = Depends(get_db)):
    """Show or hide ALL (non-required) admin pages for a group at once."""
    _valid_group(group_id)
    await RBACService.set_all_admin_pages(db, group_id, body.enabled, by=_actor(principal))
    return {"group_id": group_id, "enabled": body.enabled}


# ---------- roles (tier-1: authority, scoped to own organisation) ----------
def _role_organisation(principal: Principal) -> str:
    if not principal.organisation_id:
        raise HTTPException(status_code=400, detail="No organisation in session.")
    return principal.organisation_id


@router.get("/roles")
async def list_roles(
    user_type: Optional[str] = None,
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    principal: Principal = Depends(require_authority),
    db: AsyncSession = Depends(get_db),
):
    """Roles for the caller's organisation (envelope {items,total,limit,offset}; `q`
    matches role name/description). Roles per org are few, so paging is for API
    consistency — the page is sliced in memory over the org's (bounded) role set."""
    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    roles = await RBACService.list_roles(db, _role_organisation(principal), user_type)
    items = [{"id": str(r.id), "role_name": r.role_name, "role_key": r.role_key,
              "user_type": r.user_type, "description": r.description, "is_default": r.is_default}
             for r in roles]
    term = (q or "").strip().lower()
    if term:
        items = [x for x in items
                 if term in (x["role_name"] or "").lower()
                 or term in (x["description"] or "").lower()]
    total = len(items)
    return {"items": items[offset:offset + limit], "total": total,
            "limit": limit, "offset": offset}


@router.post("/roles")
async def create_role(
    body: RoleCreate,
    principal: Principal = Depends(require_authority),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = await RBACService.create_role(
            db, organisation_id=_role_organisation(principal), user_type=body.user_type,
            role_name=body.role_name, description=body.description,
            is_default=body.is_default, created_by=principal.user_uuid,
        )
        # The bulk allow-list write is the dynamic-staff path (no organisation ceiling).
        # Legacy teacher/student/authority roles must use the ceiling-checked
        # per-module toggle endpoints instead.
        if body.modules is not None and role.user_type == catalog.STAFF:
            await RBACService.set_role_modules(db, role, body.modules, by=_actor(principal))
        if body.creatable_role_ids is not None:
            await RBACService.set_creatable_roles(db, role.id, body.creatable_role_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(role.id), "role_name": role.role_name, "user_type": role.user_type}


async def _load_owned_role(db, principal, role_id):
    role = await RBACService.get_role(db, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if not principal.is_super_admin and str(role.organisation_id) != str(principal.organisation_id):
        raise HTTPException(status_code=403, detail="Role belongs to another organisation")
    return role


@router.put("/roles/{role_id}")
async def update_role(role_id: str, body: RoleUpdate,
                      principal: Principal = Depends(require_authority),
                      db: AsyncSession = Depends(get_db)):
    role = await _load_owned_role(db, principal, role_id)
    role = await RBACService.update_role(db, role_id, role_name=body.role_name,
                                         description=body.description, is_default=body.is_default)
    if body.modules is not None and role.user_type == catalog.STAFF:
        await RBACService.set_role_modules(db, role, body.modules, by=_actor(principal))
    if body.creatable_role_ids is not None:
        await RBACService.set_creatable_roles(db, role.id, body.creatable_role_ids)
    return {"id": str(role.id), "role_name": role.role_name}


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, principal: Principal = Depends(require_authority),
                      db: AsyncSession = Depends(get_db)):
    await _load_owned_role(db, principal, role_id)
    await RBACService.delete_role(db, role_id)
    return {"detail": "deleted"}


@router.get("/roles/{role_id}/detail")
async def role_detail(role_id: str, principal: Principal = Depends(require_authority),
                      db: AsyncSession = Depends(get_db)):
    """Full definition of a dynamic role — for the role editor to prefill."""
    role = await _load_owned_role(db, principal, role_id)
    return {
        "id": str(role.id), "role_name": role.role_name, "user_type": role.user_type,
        "description": role.description, "is_default": role.is_default,
        "modules": await RBACService.get_role_module_keys(db, role.id),
        "creatable_role_ids": await RBACService.get_creatable_role_ids(db, role.id),
    }


@router.get("/assignable-roles")
async def assignable_roles(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    """Roles the caller may assign when creating a user. Page-access model: an admin
    (authority) may assign any role in their organisation; a staff user who holds the
    "Staff & Users" page (module 'staff') may assign ANY of the organisation's roles the
    admin made — granting the page IS the grant to manage users. A staff user without that
    page gets nothing (they can't open the screen anyway)."""
    if not principal.organisation_id:
        return []
    if principal.is_authority or principal.is_super_admin:
        roles = await RBACService.list_roles(db, principal.organisation_id, "staff")
        return [{"id": str(r.id), "role_name": r.role_name, "description": r.description}
                for r in roles]
    if principal.role == "staff":
        role_id = await resolve_role_id(db, "staff", principal.user_id)
        if not role_id:
            return []
        # Holding the Staff & Users page (respecting the group pool ceiling) is what
        # lets a role manage users — it can then assign any of the org's staff roles.
        has_staff_page = await RBACService.has_module_access(
            db, user_type="staff", organisation_id=principal.organisation_id,
            role_id=role_id, module_key="staff",
        )
        if not has_staff_page:
            return []
        roles = await RBACService.list_roles(db, principal.organisation_id, "staff")
        return [{"id": str(r.id), "role_name": r.role_name, "description": r.description}
                for r in roles]
    return []


@router.get("/roles/{role_id}/permissions")
async def role_permissions(role_id: str, principal: Principal = Depends(require_authority),
                           db: AsyncSession = Depends(get_db)):
    role = await _load_owned_role(db, principal, role_id)
    return {"role_id": role_id, "user_type": role.user_type,
            "modules": await RBACService.get_role_permissions(db, role)}


@router.put("/roles/{role_id}/module/{module_key}")
async def toggle_role_module(role_id: str, module_key: str, body: ModuleToggle,
                             principal: Principal = Depends(require_authority),
                             db: AsyncSession = Depends(get_db)):
    _require_module(module_key)
    role = await _load_owned_role(db, principal, role_id)
    try:
        await RBACService.set_role_module(db, role, module_key, body.enabled, by=_actor(principal))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"detail": "updated"}


@router.put("/roles/{role_id}/module/{module_key}/tab/{tab_key}")
async def toggle_role_tab(role_id: str, module_key: str, tab_key: str, body: ModuleToggle,
                          principal: Principal = Depends(require_authority),
                          db: AsyncSession = Depends(get_db)):
    _require_tab(module_key, tab_key)
    role = await _load_owned_role(db, principal, role_id)
    try:
        await RBACService.set_role_tab(db, role, module_key, tab_key, body.enabled, by=_actor(principal))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"detail": "updated"}


@router.get("/users")
async def list_users(user_type: str, principal: Principal = Depends(require_authority),
                     db: AsyncSession = Depends(get_db)):
    """Users of a type in the caller's organisation + their currently-assigned role."""
    tbl = _IDENTITY_TABLE.get(user_type)
    if not tbl:
        raise HTTPException(status_code=400, detail="invalid user_type")
    if not principal.organisation_id:
        raise HTTPException(status_code=400, detail="No organisation in session.")
    rows = (await db.execute(text(
        f"SELECT u.id, u.first_name, u.last_name, u.phone, u.rbac_role_id, r.role_name "
        f"FROM {tbl} u LEFT JOIN rbac_roles r ON r.id = u.rbac_role_id "
        f"WHERE u.organisation_id = :t AND u.is_deleted = false "
        f"ORDER BY u.first_name, u.last_name"
    ), {"t": principal.organisation_id})).fetchall()
    return [{
        "id": str(x[0]),
        "name": f"{x[1] or ''} {x[2] or ''}".strip() or (x[3] or 'User'),
        "phone": x[3],
        "role_id": str(x[4]) if x[4] else None,
        "role_name": x[5],
    } for x in rows]


# NOTE: role assignment is done via /api/staff (StaffService, delegation-gated);
# the old POST /api/access/assign was unused by the app and had weaker rules, so
# it was removed.


# (The legacy per-organisation audience ceiling endpoints
# /organisation/{id}/permissions + /module[/tab] were removed — the ceilings are
# now per INSTITUTION GROUP, set via /group/{id}/pages + /admin-pages above.)
