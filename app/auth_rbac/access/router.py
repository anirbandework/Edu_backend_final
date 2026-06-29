"""RBAC API: my-permissions (everyone), role management (authority), tenant config (super-admin)."""
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


class TenantModuleToggle(BaseModel):
    authority_enabled: Optional[bool] = None
    teacher_enabled: Optional[bool] = None
    student_enabled: Optional[bool] = None


class AssignRole(BaseModel):
    user_type: str
    user_id: str
    role_id: Optional[str] = None  # null clears the role


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
async def _authority_granted_modules(db: AsyncSession, user_id: str):
    """The module-key set a super-admin granted this admin (in school_authorities
    .permissions JSON: {"modules":[...]}), or None if no explicit grant."""
    row = (await db.execute(
        text("SELECT permissions FROM school_authorities WHERE id = :id"),
        {"id": str(user_id)},
    )).first()
    if not row:
        return None
    perms = row[0]
    if isinstance(perms, str):
        import json as _json
        try:
            perms = _json.loads(perms)
        except Exception:
            perms = None
    if isinstance(perms, dict) and isinstance(perms.get("modules"), list):
        return set(perms["modules"])
    return None


@router.get("/my-permissions")
async def my_permissions(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    # The ADMIN's OWN sidebar is now a super-admin-controlled ceiling ("Admin
    # pages"): only the admin-audience pages the super-admin left ON for this org
    # are shown. This is SEPARATE from the distributable org ceiling (what the
    # admin may hand to their users' roles). Required pages (Profile) stay on.
    if principal.role == "school_authority":
        modules = await RBACService.get_admin_permissions(db, principal.tenant_uuid)
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
    role_id = await resolve_role_id(db, principal.role, principal.user_id)
    # Unified dynamic staff: pages come from an explicit cross-section allow-list
    # on their role (default-deny), not the audience-based catalog.
    if principal.role == "staff":
        modules = await RBACService.get_staff_permissions(db, role_id, principal.tenant_uuid)
        return {"user_type": "staff", "role_id": role_id, "modules": modules}
    modules = await RBACService.get_user_permissions(
        db, user_type=principal.role, tenant_id=principal.tenant_uuid, role_id=role_id
    )
    return {"user_type": principal.role, "role_id": role_id, "modules": modules}


@router.get("/grantable-pages")
async def grantable_pages(principal: Principal = Depends(require_authority),
                          db: AsyncSession = Depends(get_db)):
    """For the admin's Roles & Access picker: every page + a `locked` flag (the org
    doesn't have it → show 'Premium / upgrade', not assignable)."""
    return await RBACService.grantable_pages(db, principal.tenant_uuid)


# ---------- org page grant (super-admin, per organisation/tenant) ----------
def _valid_tenant(tenant_id: str) -> str:
    """Reject malformed tenant ids before they reach asyncpg (avoids a 500)."""
    try:
        import uuid as _uuid
        _uuid.UUID(str(tenant_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid organisation id")
    return tenant_id


@router.get("/org/{tenant_id}/pages")
async def org_pages(tenant_id: str, principal: Principal = Depends(require_super_admin),
                    db: AsyncSession = Depends(get_db)):
    """Per-page grant for an organisation (the super-admin's 'what they paid for')."""
    return await RBACService.get_org_pages(db, _valid_tenant(tenant_id))


@router.put("/org/{tenant_id}/page/{module_key}")
async def set_org_page(tenant_id: str, module_key: str, body: ModuleToggle,
                       principal: Principal = Depends(require_super_admin),
                       db: AsyncSession = Depends(get_db)):
    _valid_tenant(tenant_id)
    try:
        await RBACService.set_org_page(db, tenant_id, module_key, body.enabled, by=_actor(principal))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"tenant_id": tenant_id, "module_key": module_key, "enabled": body.enabled}


@router.post("/org/{tenant_id}/pages/bulk")
async def set_org_pages_bulk(tenant_id: str, body: ModuleToggle,
                             principal: Principal = Depends(require_super_admin),
                             db: AsyncSession = Depends(get_db)):
    """Enable or revoke ALL (non-required) pages for an org at once."""
    _valid_tenant(tenant_id)
    await RBACService.set_all_org_pages(db, tenant_id, body.enabled, by=_actor(principal))
    return {"tenant_id": tenant_id, "enabled": body.enabled}


# ---------- admin page grant (super-admin: which pages the ADMIN sees) ----------
@router.get("/org/{tenant_id}/admin-pages")
async def org_admin_pages(tenant_id: str, principal: Principal = Depends(require_super_admin),
                          db: AsyncSession = Depends(get_db)):
    """Per-page grant for the ADMIN's own sidebar (separate from the distributable
    org pages). Lists every admin-audience page incl. admin-only tools."""
    return await RBACService.get_admin_pages(db, _valid_tenant(tenant_id))


@router.put("/org/{tenant_id}/admin-page/{module_key}")
async def set_org_admin_page(tenant_id: str, module_key: str, body: ModuleToggle,
                             principal: Principal = Depends(require_super_admin),
                             db: AsyncSession = Depends(get_db)):
    _valid_tenant(tenant_id)
    try:
        await RBACService.set_admin_page(db, tenant_id, module_key, body.enabled, by=_actor(principal))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"tenant_id": tenant_id, "module_key": module_key, "enabled": body.enabled}


@router.post("/org/{tenant_id}/admin-pages/bulk")
async def set_org_admin_pages_bulk(tenant_id: str, body: ModuleToggle,
                                   principal: Principal = Depends(require_super_admin),
                                   db: AsyncSession = Depends(get_db)):
    """Show or hide ALL (non-required) admin pages for an org at once."""
    _valid_tenant(tenant_id)
    await RBACService.set_all_admin_pages(db, tenant_id, body.enabled, by=_actor(principal))
    return {"tenant_id": tenant_id, "enabled": body.enabled}


# ---------- roles (tier-1: school authority, scoped to own tenant) ----------
def _role_tenant(principal: Principal) -> str:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="No tenant in session.")
    return principal.tenant_id


@router.get("/roles")
async def list_roles(
    user_type: Optional[str] = None,
    principal: Principal = Depends(require_authority),
    db: AsyncSession = Depends(get_db),
):
    roles = await RBACService.list_roles(db, _role_tenant(principal), user_type)
    return [{"id": str(r.id), "role_name": r.role_name, "role_key": r.role_key,
             "user_type": r.user_type, "description": r.description, "is_default": r.is_default}
            for r in roles]


@router.post("/roles")
async def create_role(
    body: RoleCreate,
    principal: Principal = Depends(require_authority),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = await RBACService.create_role(
            db, tenant_id=_role_tenant(principal), user_type=body.user_type,
            role_name=body.role_name, description=body.description,
            is_default=body.is_default, created_by=principal.user_uuid,
        )
        # The bulk allow-list write is the dynamic-staff path (no tenant ceiling).
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
    if not principal.is_super_admin and str(role.tenant_id) != str(principal.tenant_id):
        raise HTTPException(status_code=403, detail="Role belongs to another school")
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
    """Roles the caller may assign when creating a user. An admin (authority) may
    assign any role in their school; a staff user may assign only the roles their
    own role was delegated to create."""
    if not principal.tenant_id:
        return []
    if principal.is_authority or principal.is_super_admin:
        roles = await RBACService.list_roles(db, principal.tenant_id, "staff")
        return [{"id": str(r.id), "role_name": r.role_name, "description": r.description}
                for r in roles]
    if principal.role == "staff":
        role_id = await resolve_role_id(db, "staff", principal.user_id)
        if not role_id:
            return []
        ids = await RBACService.get_creatable_role_ids(db, role_id)
        out = []
        for cid in ids:
            r = await RBACService.get_role(db, cid)
            if r and str(r.tenant_id) == str(principal.tenant_id):
                out.append({"id": str(r.id), "role_name": r.role_name, "description": r.description})
        return out
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
    """Users of a type in the caller's tenant + their currently-assigned role."""
    tbl = _IDENTITY_TABLE.get(user_type)
    if not tbl:
        raise HTTPException(status_code=400, detail="invalid user_type")
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="No tenant in session.")
    rows = (await db.execute(text(
        f"SELECT u.id, u.first_name, u.last_name, u.phone, u.rbac_role_id, r.role_name "
        f"FROM {tbl} u LEFT JOIN rbac_roles r ON r.id = u.rbac_role_id "
        f"WHERE u.tenant_id = :t AND u.is_deleted = false "
        f"ORDER BY u.first_name, u.last_name"
    ), {"t": principal.tenant_id})).fetchall()
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


# ---------- tenant ceiling (tier-0: super-admin) ----------
@router.get("/tenant/{tenant_id}/permissions")
async def tenant_permissions(tenant_id: str, principal: Principal = Depends(require_super_admin),
                             db: AsyncSession = Depends(get_db)):
    return {"tenant_id": tenant_id, "modules": await RBACService.get_tenant_permissions(db, tenant_id)}


@router.put("/tenant/{tenant_id}/module/{module_key}")
async def toggle_tenant_module(tenant_id: str, module_key: str, body: TenantModuleToggle,
                               principal: Principal = Depends(require_super_admin),
                               db: AsyncSession = Depends(get_db)):
    _require_module(module_key)
    await RBACService.set_tenant_module(db, tenant_id, module_key,
                                        authority=body.authority_enabled, teacher=body.teacher_enabled,
                                        student=body.student_enabled, by=principal.role)
    return {"detail": "updated"}


@router.put("/tenant/{tenant_id}/module/{module_key}/tab/{tab_key}")
async def toggle_tenant_tab(tenant_id: str, module_key: str, tab_key: str, body: ModuleToggle,
                            principal: Principal = Depends(require_super_admin),
                            db: AsyncSession = Depends(get_db)):
    _require_tab(module_key, tab_key)
    await RBACService.set_tenant_tab(db, tenant_id, module_key, tab_key, body.enabled, by=principal.role)
    return {"detail": "updated"}
