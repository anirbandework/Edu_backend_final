"""RBACService — permission resolution + role/organisation CRUD (module model).

Ceilings are now per INSTITUTION GROUP (not per organisation): the super-admin sets,
per group, (a) the role page-pool (role_enabled) and (b) the admin pages
(admin_enabled). Both apply to every organisation in the group. Resolution
functions still receive an `organisation_id` and resolve its group internally;
the super-admin editor functions take a `group_id` directly. RBAC roles stay
per-organisation.
"""
from __future__ import annotations
import re
import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog
from .catalog import MODULES, PREMIUM_MODULE_KEYS, get_module, modules_for, AUTHORITY
from .models import (
    RbacRole, GroupModulePermission, GroupTabPermission,
    RoleModulePermission, RoleTabPermission,
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_") or "role"


class RBACService:
    # ---------------- org → group resolution ----------------
    @staticmethod
    async def group_id_for_org(db: AsyncSession, organisation_id):
        """The institution group an organisation belongs to (ceilings live there)."""
        if not organisation_id:
            return None
        from ...organisation_management.models.organisation import Organisation
        return (await db.execute(
            select(Organisation.group_id).where(Organisation.id == organisation_id)
        )).scalar_one_or_none()

    # ---------------- group ceiling reads (keyed by group_id) ----------------
    @staticmethod
    async def _group_role_map(db, group_id) -> dict:
        """{module_key: in_group_pool_bool}. Default ON (no row), unless premium."""
        rows = []
        if group_id:
            rows = (await db.execute(
                select(GroupModulePermission).where(GroupModulePermission.group_id == group_id)
            )).scalars().all()
        explicit = {r.module_key: bool(r.role_enabled) for r in rows}
        return {m["module_key"]: explicit.get(m["module_key"], m["module_key"] not in PREMIUM_MODULE_KEYS)
                for m in MODULES}

    @staticmethod
    async def _group_admin_map(db, group_id) -> dict:
        """{module_key: admin_can_see_it}. Default ON (no row)."""
        rows = []
        if group_id:
            rows = (await db.execute(
                select(GroupModulePermission).where(GroupModulePermission.group_id == group_id)
            )).scalars().all()
        explicit = {r.module_key: bool(r.admin_enabled) for r in rows}
        return {m["module_key"]: explicit.get(m["module_key"], True) for m in MODULES}

    @staticmethod
    async def _group_role_enabled(db, group_id, module_key) -> bool:
        if not group_id:
            return module_key not in PREMIUM_MODULE_KEYS
        row = (await db.execute(
            select(GroupModulePermission).where(
                GroupModulePermission.group_id == group_id,
                GroupModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        return bool(row.role_enabled) if row is not None else (module_key not in PREMIUM_MODULE_KEYS)

    @staticmethod
    async def _group_tab_enabled(db, group_id, module_key, tab_key) -> bool:
        row = (await db.execute(
            select(GroupTabPermission).where(
                GroupTabPermission.group_id == group_id,
                GroupTabPermission.module_key == module_key,
                GroupTabPermission.tab_key == tab_key,
            )
        )).scalar_one_or_none()
        return row.enabled if row else True

    # ---------------- resolution (org-scoped callers) ----------------
    @staticmethod
    async def organisation_has_page(db, organisation_id, module_key) -> bool:
        """Group POOL ceiling: may an organisation in this org's GROUP use this page
        at all (= what the super-admin granted the group)? No row => default granted
        (unless premium)."""
        gid = await RBACService.group_id_for_org(db, organisation_id)
        return await RBACService._group_role_enabled(db, gid, module_key)

    @staticmethod
    async def organisation_admin_has_page(db, organisation_id, module_key) -> bool:
        """ADMIN ceiling: may this org's group's ADMINS use/see this page
        (admin_enabled)? Required pages are always on; no row => default True, so
        this only denies a page the super-admin EXPLICITLY revoked."""
        m = get_module(module_key)
        if m and m.get("required"):
            return True
        gid = await RBACService.group_id_for_org(db, organisation_id)
        if not gid:
            return True
        amap = await RBACService._group_admin_map(db, gid)
        return amap.get(module_key, True)

    @staticmethod
    async def has_module_access(
        db: AsyncSession, *, user_type: str, organisation_id, role_id, module_key: str
    ) -> bool:
        """Server-side gate. group POOL ceiling AND the role's allow-list grant.
        For 'staff' this is an EXPLICIT allow-list (a module is accessible only if
        the role has a RoleModulePermission row with enabled=True)."""
        m = get_module(module_key)
        if not m:
            return False
        if m.get("required"):
            return True  # e.g. Profile — always accessible
        if not await RBACService.organisation_has_page(db, organisation_id, module_key):
            return False  # group pool doesn't include this page
        if not role_id:
            return False
        rp = (await db.execute(
            select(RoleModulePermission).where(
                RoleModulePermission.role_id == role_id,
                RoleModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        return bool(rp and rp.enabled)

    # ---------------- roles (tier-1, per organisation) ----------------
    @staticmethod
    async def list_roles(db, organisation_id, user_type: Optional[str] = None):
        stmt = select(RbacRole).where(RbacRole.organisation_id == organisation_id)
        if hasattr(RbacRole, "is_deleted"):
            stmt = stmt.where(RbacRole.is_deleted == False)  # noqa: E712
        if user_type:
            stmt = stmt.where(RbacRole.user_type == user_type)
        return (await db.execute(stmt.order_by(RbacRole.user_type, RbacRole.role_name))).scalars().all()

    @staticmethod
    async def create_role(db, *, organisation_id, user_type, role_name, description=None, is_default=False, created_by=None):
        if user_type not in catalog.ROLE_USER_TYPES:
            raise ValueError(f"invalid user_type {user_type}")
        role = RbacRole(
            organisation_id=organisation_id, user_type=user_type, role_name=role_name,
            role_key=_slug(role_name), description=description, is_default=is_default,
            created_by=created_by,
        )
        db.add(role)
        try:
            if is_default:
                await db.flush()
                await RBACService._clear_other_defaults(db, organisation_id, user_type, role.id)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ValueError(f"A {user_type.replace('_', ' ')} role named '{role_name}' already exists.")
        await db.refresh(role)
        return role

    @staticmethod
    async def _clear_other_defaults(db, organisation_id, user_type, keep_id):
        rows = (await db.execute(
            select(RbacRole).where(
                RbacRole.organisation_id == organisation_id, RbacRole.user_type == user_type,
                RbacRole.is_default == True, RbacRole.id != keep_id,  # noqa: E712
            )
        )).scalars().all()
        for r in rows:
            r.is_default = False

    @staticmethod
    async def get_role(db, role_id, include_deleted: bool = False):
        stmt = select(RbacRole).where(RbacRole.id == role_id)
        if not include_deleted and hasattr(RbacRole, "is_deleted"):
            stmt = stmt.where(RbacRole.is_deleted == False)  # noqa: E712
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def update_role(db, role_id, *, role_name=None, description=None, is_default=None):
        role = await RBACService.get_role(db, role_id)
        if not role:
            return None
        if role_name is not None:
            role.role_name = role_name
            role.role_key = _slug(role_name)
        if description is not None:
            role.description = description
        if is_default is not None:
            role.is_default = is_default
            if is_default:
                await db.flush()
                await RBACService._clear_other_defaults(db, role.organisation_id, role.user_type, role.id)
        await db.commit()
        await db.refresh(role)
        return role

    @staticmethod
    async def delete_role(db, role_id) -> bool:
        role = await RBACService.get_role(db, role_id)
        if not role:
            return False
        # Unassign users pointing at this role (they fall back to the deny-list
        # defaults), then hard-delete so its permission rows cascade away and the
        # (organisation,type,key) name can be reused.
        for tbl in ("authorities", "members"):
            await db.execute(text(f"UPDATE {tbl} SET rbac_role_id = NULL WHERE rbac_role_id = :rid"),
                             {"rid": str(role.id)})
        await db.delete(role)
        await db.commit()
        return True

    @staticmethod
    async def get_default_role_id(db, organisation_id, user_type):
        r = (await db.execute(
            select(RbacRole).where(
                RbacRole.organisation_id == organisation_id, RbacRole.user_type == user_type,
                RbacRole.is_default == True,  # noqa: E712
                RbacRole.is_deleted == False,  # noqa: E712
            ).limit(1)
        )).scalar_one_or_none()
        return r.id if r else None

    # ---------------- role permissions (tier-1, ceiling-checked) ----------------
    @staticmethod
    async def get_role_permissions(db, role) -> list[dict]:
        """The page list for this role with its enabled flags (role-editor UI)."""
        return await RBACService.get_staff_permissions(db, role.id, role.organisation_id)

    @staticmethod
    async def set_role_module(db, role, module_key, enabled: bool, by=None):
        if enabled and not await RBACService.organisation_has_page(db, role.organisation_id, module_key):
            raise PermissionError("Page not in this group's plan (set by the platform admin).")
        row = (await db.execute(
            select(RoleModulePermission).where(
                RoleModulePermission.role_id == role.id,
                RoleModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        if row:
            row.enabled = enabled
        else:
            db.add(RoleModulePermission(role_id=role.id, module_key=module_key, enabled=enabled, configured_by=by))
        await db.commit()

    @staticmethod
    async def set_role_tab(db, role, module_key, tab_key, enabled: bool, by=None):
        gid = await RBACService.group_id_for_org(db, role.organisation_id)
        if enabled and not await RBACService._group_tab_enabled(db, gid, module_key, tab_key):
            raise PermissionError("Tab not in this group's plan (set by the platform admin).")
        row = (await db.execute(
            select(RoleTabPermission).where(
                RoleTabPermission.role_id == role.id,
                RoleTabPermission.module_key == module_key,
                RoleTabPermission.tab_key == tab_key,
            )
        )).scalar_one_or_none()
        if row:
            row.enabled = enabled
        else:
            db.add(RoleTabPermission(role_id=role.id, module_key=module_key, tab_key=tab_key, enabled=enabled, configured_by=by))
        await db.commit()

    # ---------------- unified dynamic staff roles ----------------
    @staticmethod
    async def get_staff_permissions(db, role_id, organisation_id=None) -> list[dict]:
        """Effective page list for a STAFF user: role allow-list INTERSECTED with the
        group pool. `enabled` = role granted AND group granted. `locked` = the group
        doesn't have this page ("premium / not in plan")."""
        rperm = {}
        if role_id:
            rperm = {
                r.module_key: r.enabled
                for r in (await db.execute(
                    select(RoleModulePermission).where(RoleModulePermission.role_id == role_id)
                )).scalars().all()
            }
        gid = await RBACService.group_id_for_org(db, organisation_id)
        ceiling = await RBACService._group_role_map(db, gid)
        out = []
        for m in MODULES:
            key = m["module_key"]
            grp_ok = ceiling.get(key, True)
            role_ok = bool(rperm.get(key, False))  # default-DENY for staff
            enabled = role_ok and grp_ok
            locked = (not grp_ok)
            if m.get("required"):
                enabled = True   # e.g. Profile — always on for everyone
                locked = False
            out.append({
                "module_key": key, "module_name": m["module_name"], "icon": m["icon"],
                "path": m["path"], "section": m.get("section"), "enabled": enabled,
                "required": bool(m.get("required")),
                "locked": locked,
                "tabs": [{"tab_key": tk, "tab_label": tl} for tk, tl in m["tabs"]],
                "tab_permissions": {tk: enabled for tk, _ in m["tabs"]},
                "locked_tabs": {},
            })
        return out

    @staticmethod
    async def grantable_pages(db, organisation_id) -> list[dict]:
        """Catalog for the admin's role-permission picker — ONLY pages a 'staff' role
        can actually use. Each carries `locked` = the group doesn't have it
        (→ 'Premium/upgrade'). Required pages are never locked."""
        gid = await RBACService.group_id_for_org(db, organisation_id)
        ceiling = await RBACService._group_role_map(db, gid)
        out = []
        for m in MODULES:
            if m.get("admin_only") or not m.get("staff_grantable", True):
                continue
            key = m["module_key"]
            locked = (not ceiling.get(key, True)) and not m.get("required")
            out.append({
                "module_key": key, "module_name": m["module_name"], "icon": m["icon"],
                "path": m["path"], "section": m.get("section"),
                "audience_group": m.get("audience_group"),
                "required": bool(m.get("required")), "locked": locked,
            })
        return out

    @staticmethod
    async def set_role_modules(db, role, module_keys: list[str], by=None):
        """Replace a role's granted modules with exactly `module_keys` (enabled).
        Allow-list semantics: anything not listed is removed. Pages outside the group
        pool (locked) and admin-only / non-staff-grantable pages are dropped."""
        candidate = {mk for mk in module_keys if get_module(mk)}
        valid = set()
        for mk in candidate:
            m = get_module(mk)
            if m.get("admin_only") or not m.get("staff_grantable", True):
                continue
            if not m.get("required") and not await RBACService.organisation_has_page(db, role.organisation_id, mk):
                continue  # group doesn't have this page → can't be granted
            valid.add(mk)
        existing = {
            r.module_key: r
            for r in (await db.execute(
                select(RoleModulePermission).where(RoleModulePermission.role_id == role.id)
            )).scalars().all()
        }
        for mk in valid:
            if mk in existing:
                existing[mk].enabled = True
            else:
                db.add(RoleModulePermission(role_id=role.id, module_key=mk, enabled=True, configured_by=by))
        for mk, row in existing.items():
            if mk not in valid:
                await db.delete(row)
        await db.commit()

    @staticmethod
    async def get_role_module_keys(db, role_id) -> list[str]:
        rows = (await db.execute(
            select(RoleModulePermission).where(
                RoleModulePermission.role_id == role_id,
                RoleModulePermission.enabled == True,  # noqa: E712
            )
        )).scalars().all()
        return [r.module_key for r in rows]

    @staticmethod
    async def set_creatable_roles(db, role_id, creatable_role_ids: list[str]):
        """Replace which roles a holder of `role_id` may create users into. Only
        roles in the SAME organisation with user_type 'staff' are kept."""
        from .models import RoleCreatableRole
        owner = await RBACService.get_role(db, role_id)
        if not owner:
            return
        candidates = []
        for c in (creatable_role_ids or []):
            s = str(c).strip()
            if not s or s == str(role_id):
                continue
            try:
                uuid.UUID(s)
            except (ValueError, TypeError, AttributeError):
                continue
            candidates.append(s)
        valid = set()
        if candidates:
            rows = (await db.execute(
                select(RbacRole.id).where(
                    RbacRole.id.in_(candidates),
                    RbacRole.organisation_id == owner.organisation_id,
                    RbacRole.user_type == catalog.STAFF,
                    RbacRole.is_deleted == False,  # noqa: E712
                )
            )).scalars().all()
            valid = {str(r) for r in rows}
        existing = {
            str(r.creatable_role_id): r
            for r in (await db.execute(
                select(RoleCreatableRole).where(RoleCreatableRole.role_id == role_id)
            )).scalars().all()
        }
        for cid in valid:
            if cid not in existing:
                db.add(RoleCreatableRole(role_id=role_id, creatable_role_id=cid))
        for cid, row in existing.items():
            if cid not in valid:
                await db.delete(row)
        await db.commit()

    @staticmethod
    async def get_creatable_role_ids(db, role_id) -> list[str]:
        from .models import RoleCreatableRole
        rows = (await db.execute(
            select(RoleCreatableRole).where(RoleCreatableRole.role_id == role_id)
        )).scalars().all()
        return [str(r.creatable_role_id) for r in rows]

    # ============ super-admin ceiling editor (PER GROUP) ============
    # The two ceilings live on group_module_permissions: role_enabled (the page
    # pool admins grant to roles) and admin_enabled (the admins' own sidebar).

    @staticmethod
    async def set_group_module(db, group_id, module_key, *, role=None, admin=None, by=None, commit=True):
        row = (await db.execute(
            select(GroupModulePermission).where(
                GroupModulePermission.group_id == group_id,
                GroupModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        if not row:
            default = module_key not in PREMIUM_MODULE_KEYS
            row = GroupModulePermission(
                group_id=group_id, module_key=module_key,
                role_enabled=default, admin_enabled=True, configured_by=by,
            )
            db.add(row)
        if role is not None:
            row.role_enabled = role
        if admin is not None:
            row.admin_enabled = admin
        if by:
            row.configured_by = by
        # `commit=False` lets the bulk setters flush every page in ONE transaction
        # (one round-trip) instead of committing per module.
        if commit:
            await db.commit()

    # ---- ceiling (a): the role page-pool, per group ----
    @staticmethod
    async def get_group_pages(db, group_id) -> list[dict]:
        """Per-page POOL grant for the super-admin's 'Group pages' editor. Excludes
        admin-only tools (those are the admins' own constant toolset)."""
        ceiling = await RBACService._group_role_map(db, group_id)
        return [{
            "module_key": m["module_key"], "module_name": m["module_name"], "icon": m["icon"],
            "path": m["path"], "section": m.get("section"), "audience_group": m.get("audience_group"),
            "required": bool(m.get("required")),
            "enabled": True if m.get("required") else ceiling.get(m["module_key"], True),
        } for m in MODULES if not m.get("admin_only")]

    @staticmethod
    async def set_group_page(db, group_id, module_key, enabled: bool, by=None):
        m = get_module(module_key)
        if not m:
            raise ValueError("Unknown page")
        if m.get("required") or m.get("admin_only"):
            return
        await RBACService.set_group_module(db, group_id, module_key, role=enabled, by=by)

    @staticmethod
    async def set_all_group_pages(db, group_id, enabled: bool, by=None):
        for m in MODULES:
            if m.get("required") or m.get("admin_only"):
                continue
            await RBACService.set_group_module(db, group_id, m["module_key"], role=enabled, by=by, commit=False)
        await db.commit()  # one transaction for the whole bulk change

    # ---- ceiling (b): the admin pages, per group ----
    @staticmethod
    async def get_admin_permissions(db, organisation_id) -> list[dict]:
        """The ADMIN's own sidebar = admin-audience pages the super-admin left ON for
        the org's GROUP (admin_enabled). Required pages always on. Shape matches a
        my-permissions module entry so the client can gate on it."""
        gid = await RBACService.group_id_for_org(db, organisation_id)
        ceiling = await RBACService._group_admin_map(db, gid)
        out = []
        for m in modules_for(AUTHORITY):
            enabled = True if m.get("required") else ceiling.get(m["module_key"], True)
            out.append({
                "module_key": m["module_key"], "module_name": m["module_name"], "icon": m["icon"],
                "path": m["path"], "enabled": enabled, "required": bool(m.get("required")), "locked": False,
                "tabs": [{"tab_key": t[0], "tab_label": t[1]} for t in m["tabs"]],
                "tab_permissions": {t[0]: True for t in m["tabs"]}, "locked_tabs": {},
            })
        return out

    @staticmethod
    async def get_admin_pages(db, group_id) -> list[dict]:
        """Per-page ADMIN grant for the super-admin's 'Admin pages' editor (per group)."""
        ceiling = await RBACService._group_admin_map(db, group_id)
        return [{
            "module_key": m["module_key"], "module_name": m["module_name"], "icon": m["icon"],
            "path": m["path"], "section": m.get("section"), "audience_group": m.get("audience_group"),
            "required": bool(m.get("required")),
            "enabled": True if m.get("required") else ceiling.get(m["module_key"], True),
        } for m in modules_for(AUTHORITY)]

    @staticmethod
    async def set_admin_page(db, group_id, module_key, enabled: bool, by=None):
        m = get_module(module_key)
        if not m:
            raise ValueError("Unknown page")
        if m.get("required"):
            return
        await RBACService.set_group_module(db, group_id, module_key, admin=enabled, by=by)

    @staticmethod
    async def set_all_admin_pages(db, group_id, enabled: bool, by=None):
        for m in modules_for(AUTHORITY):
            if m.get("required"):
                continue
            await RBACService.set_group_module(db, group_id, m["module_key"], admin=enabled, by=by, commit=False)
        await db.commit()  # one transaction for the whole bulk change

    @staticmethod
    async def set_group_tab(db, group_id, module_key, tab_key, enabled: bool, by=None):
        row = (await db.execute(
            select(GroupTabPermission).where(
                GroupTabPermission.group_id == group_id,
                GroupTabPermission.module_key == module_key,
                GroupTabPermission.tab_key == tab_key,
            )
        )).scalar_one_or_none()
        if row:
            row.enabled = enabled
        else:
            db.add(GroupTabPermission(group_id=group_id, module_key=module_key, tab_key=tab_key, enabled=enabled, configured_by=by))
        await db.commit()
