"""RBACService — permission resolution + role/tenant CRUD (module/tab model)."""
from __future__ import annotations
import re
import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog
from .catalog import MODULES, PREMIUM_MODULE_KEYS, get_module, modules_for, enabled_field
from .models import (
    RbacRole, TenantModulePermission, TenantTabPermission,
    RoleModulePermission, RoleTabPermission,
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_") or "role"


class RBACService:
    # ---------------- resolution ----------------
    @staticmethod
    async def get_user_permissions(
        db: AsyncSession, *, user_type: str, tenant_id, role_id=None
    ) -> list[dict]:
        """Full module list (for the caller's audience) with effective enabled +
        per-tab permissions. Super-admin should not call this (it sees everything)."""
        tperm = {
            r.module_key: r
            for r in (await db.execute(
                select(TenantModulePermission).where(TenantModulePermission.tenant_id == tenant_id)
            )).scalars().all()
        }
        ttab = {
            (r.module_key, r.tab_key): r.enabled
            for r in (await db.execute(
                select(TenantTabPermission).where(TenantTabPermission.tenant_id == tenant_id)
            )).scalars().all()
        }
        rperm, rtab = {}, {}
        if role_id:
            rperm = {
                r.module_key: r.enabled
                for r in (await db.execute(
                    select(RoleModulePermission).where(RoleModulePermission.role_id == role_id)
                )).scalars().all()
            }
            rtab = {
                (r.module_key, r.tab_key): r.enabled
                for r in (await db.execute(
                    select(RoleTabPermission).where(RoleTabPermission.role_id == role_id)
                )).scalars().all()
            }

        field = enabled_field(user_type)
        out = []
        for m in modules_for(user_type):
            key = m["module_key"]
            tp = tperm.get(key)
            org_enabled = getattr(tp, field) if tp else (key not in PREMIUM_MODULE_KEYS)
            role_enabled = rperm.get(key, True) if role_id else True
            module_enabled = bool(org_enabled and role_enabled)
            if m.get("required"):
                module_enabled = True  # e.g. Profile — always on

            tab_perms, locked_tabs, tabs_meta = {}, {}, []
            for tk, tl in m["tabs"]:
                org_tab = ttab.get((key, tk), True)
                role_tab = rtab.get((key, tk), True) if role_id else True
                tab_perms[tk] = bool(org_tab and role_tab)
                if not org_tab:
                    locked_tabs[tk] = True
                tabs_meta.append({"tab_key": tk, "tab_label": tl})

            out.append({
                "module_key": key,
                "module_name": m["module_name"],
                "icon": m["icon"],
                "path": m["path"],
                "enabled": module_enabled,
                "required": bool(m.get("required")),
                "locked": (not org_enabled),
                "tabs": tabs_meta,
                "tab_permissions": tab_perms,
                "locked_tabs": locked_tabs,
            })
        return out

    @staticmethod
    async def has_module_access(
        db: AsyncSession, *, user_type: str, tenant_id, role_id, module_key: str
    ) -> bool:
        """Server-side gate. tenant_enabled AND role_enabled (deny-list defaults).

        For the unified 'staff' user_type this is an EXPLICIT allow-list: a module
        is accessible only if the role has a RoleModulePermission row with
        enabled=True (no audience / tenant-ceiling gating)."""
        if user_type == catalog.STAFF:
            m = get_module(module_key)
            if not m:
                return False
            if m.get("required"):
                return True  # e.g. Profile — always accessible
            # org ceiling: the page must be granted to this org (what they "paid for")
            if not await RBACService.tenant_has_page(db, tenant_id, module_key):
                return False
            if not role_id:
                return False
            rp = (await db.execute(
                select(RoleModulePermission).where(
                    RoleModulePermission.role_id == role_id,
                    RoleModulePermission.module_key == module_key,
                )
            )).scalar_one_or_none()
            return bool(rp and rp.enabled)
        m = get_module(module_key)
        if not m or user_type not in m["audience"]:
            return False
        tp = (await db.execute(
            select(TenantModulePermission).where(
                TenantModulePermission.tenant_id == tenant_id,
                TenantModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        org_enabled = getattr(tp, enabled_field(user_type)) if tp else (module_key not in PREMIUM_MODULE_KEYS)
        if not org_enabled:
            return False
        if role_id:
            rp = (await db.execute(
                select(RoleModulePermission).where(
                    RoleModulePermission.role_id == role_id,
                    RoleModulePermission.module_key == module_key,
                )
            )).scalar_one_or_none()
            if rp is not None and not rp.enabled:
                return False
        return True

    @staticmethod
    async def _tenant_module_allowed(db, tenant_id, user_type, module_key) -> bool:
        tp = (await db.execute(
            select(TenantModulePermission).where(
                TenantModulePermission.tenant_id == tenant_id,
                TenantModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        return getattr(tp, enabled_field(user_type)) if tp else (module_key not in PREMIUM_MODULE_KEYS)

    @staticmethod
    async def tenant_has_page(db, tenant_id, module_key) -> bool:
        """ORG-LEVEL ceiling (audience-agnostic): may this organisation use this
        page at all? = what the super-admin granted the org ("paid for"). No row
        => default granted (unless premium). A page is on for the org if it's on
        for any audience column."""
        if not tenant_id:
            return module_key not in PREMIUM_MODULE_KEYS
        tp = (await db.execute(
            select(TenantModulePermission).where(
                TenantModulePermission.tenant_id == tenant_id,
                TenantModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        if tp is None:
            return module_key not in PREMIUM_MODULE_KEYS
        return bool(tp.authority_enabled or tp.teacher_enabled or tp.student_enabled)

    @staticmethod
    async def _org_ceiling_map(db, tenant_id) -> dict:
        """{module_key: org_granted_bool} for a tenant, from one query (default
        ON for modules with no row, unless premium)."""
        rows = []
        if tenant_id:
            rows = (await db.execute(
                select(TenantModulePermission).where(TenantModulePermission.tenant_id == tenant_id)
            )).scalars().all()
        explicit = {r.module_key: bool(r.authority_enabled or r.teacher_enabled or r.student_enabled)
                    for r in rows}
        return {m["module_key"]: explicit.get(m["module_key"], m["module_key"] not in PREMIUM_MODULE_KEYS)
                for m in MODULES}

    @staticmethod
    async def _tenant_tab_allowed(db, tenant_id, module_key, tab_key) -> bool:
        row = (await db.execute(
            select(TenantTabPermission).where(
                TenantTabPermission.tenant_id == tenant_id,
                TenantTabPermission.module_key == module_key,
                TenantTabPermission.tab_key == tab_key,
            )
        )).scalar_one_or_none()
        return row.enabled if row else True

    # ---------------- roles (tier-1) ----------------
    @staticmethod
    async def list_roles(db, tenant_id, user_type: Optional[str] = None):
        stmt = select(RbacRole).where(RbacRole.tenant_id == tenant_id)
        if hasattr(RbacRole, "is_deleted"):
            stmt = stmt.where(RbacRole.is_deleted == False)  # noqa: E712
        if user_type:
            stmt = stmt.where(RbacRole.user_type == user_type)
        return (await db.execute(stmt.order_by(RbacRole.user_type, RbacRole.role_name))).scalars().all()

    @staticmethod
    async def create_role(db, *, tenant_id, user_type, role_name, description=None, is_default=False, created_by=None):
        if user_type not in catalog.ROLE_USER_TYPES:
            raise ValueError(f"invalid user_type {user_type}")
        role = RbacRole(
            tenant_id=tenant_id, user_type=user_type, role_name=role_name,
            role_key=_slug(role_name), description=description, is_default=is_default,
            created_by=created_by,
        )
        db.add(role)
        try:
            if is_default:
                await db.flush()
                await RBACService._clear_other_defaults(db, tenant_id, user_type, role.id)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ValueError(f"A {user_type.replace('_', ' ')} role named '{role_name}' already exists.")
        await db.refresh(role)
        return role

    @staticmethod
    async def _clear_other_defaults(db, tenant_id, user_type, keep_id):
        rows = (await db.execute(
            select(RbacRole).where(
                RbacRole.tenant_id == tenant_id, RbacRole.user_type == user_type,
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
                await RBACService._clear_other_defaults(db, role.tenant_id, role.user_type, role.id)
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
        # (tenant,type,key) name can be reused. Avoids stale/zombie permissions.
        for tbl in ("school_authorities", "teachers", "students", "staff_users"):
            await db.execute(text(f"UPDATE {tbl} SET rbac_role_id = NULL WHERE rbac_role_id = :rid"),
                             {"rid": str(role.id)})
        await db.delete(role)
        await db.commit()
        return True

    @staticmethod
    async def get_default_role_id(db, tenant_id, user_type):
        r = (await db.execute(
            select(RbacRole).where(
                RbacRole.tenant_id == tenant_id, RbacRole.user_type == user_type,
                RbacRole.is_default == True,  # noqa: E712
                RbacRole.is_deleted == False,  # noqa: E712
            ).limit(1)
        )).scalar_one_or_none()
        return r.id if r else None

    # ---------------- role permissions (tier-1, ceiling-checked) ----------------
    @staticmethod
    async def get_role_permissions(db, role) -> list[dict]:
        """The full module list for this role's user_type, with the role's
        enabled flags (for the admin role-editor UI)."""
        # Dynamic 'staff' roles aren't in the audience-based catalog and have no
        # tenant-ceiling column (enabled_field would KeyError); use the
        # cross-section allow-list view instead.
        if role.user_type == catalog.STAFF:
            return await RBACService.get_staff_permissions(db, role.id, role.tenant_id)
        return await RBACService.get_user_permissions(
            db, user_type=role.user_type, tenant_id=role.tenant_id, role_id=role.id
        )

    @staticmethod
    async def _role_ceiling_ok(db, role, module_key) -> bool:
        """Is `module_key` within the org ceiling for this role? Staff roles use the
        audience-agnostic ceiling (enabled_field has no 'staff' column → would
        KeyError); other roles use their audience column."""
        if role.user_type == catalog.STAFF:
            return await RBACService.tenant_has_page(db, role.tenant_id, module_key)
        return await RBACService._tenant_module_allowed(db, role.tenant_id, role.user_type, module_key)

    @staticmethod
    async def set_role_module(db, role, module_key, enabled: bool, by=None):
        if enabled and not await RBACService._role_ceiling_ok(db, role, module_key):
            raise PermissionError("Module not enabled for this school by the platform admin.")
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
        if enabled and not await RBACService._tenant_tab_allowed(db, role.tenant_id, module_key, tab_key):
            raise PermissionError("Tab not enabled for this school by the platform admin.")
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
    async def get_staff_permissions(db, role_id, tenant_id=None) -> list[dict]:
        """Effective module list for a STAFF user: role allow-list INTERSECTED with
        the org ceiling. `enabled` = role granted AND org granted. `locked` = the
        org doesn't have this page ("premium / not in plan") — distinct from a page
        the admin simply hasn't assigned to the role."""
        rperm = {}
        if role_id:
            rperm = {
                r.module_key: r.enabled
                for r in (await db.execute(
                    select(RoleModulePermission).where(RoleModulePermission.role_id == role_id)
                )).scalars().all()
            }
        ceiling = await RBACService._org_ceiling_map(db, tenant_id)
        out = []
        for m in MODULES:
            key = m["module_key"]
            org_ok = ceiling.get(key, True)
            role_ok = bool(rperm.get(key, False))  # default-DENY for staff
            enabled = role_ok and org_ok
            locked = (not org_ok)
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
    async def grantable_pages(db, tenant_id) -> list[dict]:
        """Catalog for the admin's role-permission picker — ONLY pages a dynamic
        'staff' role can actually use (excludes admin-only + teacher/student-coupled
        pages whose endpoints would 403 for staff). Each carries `locked` = the org
        doesn't have it (→ 'Premium/upgrade', not assignable). Required pages are
        never locked."""
        ceiling = await RBACService._org_ceiling_map(db, tenant_id)
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

    # ---------------- org page grant (super-admin, per tenant) ----------------
    @staticmethod
    async def get_org_pages(db, tenant_id) -> list[dict]:
        """Per-page org grant for the super-admin's org editor. Excludes admin-only
        pages (those are the admin's own constant tools, not part of an org plan)."""
        ceiling = await RBACService._org_ceiling_map(db, tenant_id)
        return [{
            "module_key": m["module_key"], "module_name": m["module_name"], "icon": m["icon"],
            "path": m["path"], "section": m.get("section"), "audience_group": m.get("audience_group"),
            "required": bool(m.get("required")),
            "enabled": True if m.get("required") else ceiling.get(m["module_key"], True),
        } for m in MODULES if not m.get("admin_only")]

    @staticmethod
    async def set_org_page(db, tenant_id, module_key, enabled: bool, by=None):
        """Grant/revoke a single page for an org — sets all audience columns the
        same (audience-agnostic org ceiling). Required/admin-only pages are no-ops."""
        m = get_module(module_key)
        if not m:
            raise ValueError("Unknown page")
        if m.get("required") or m.get("admin_only"):
            return  # always-on / not part of the org plan
        await RBACService.set_tenant_module(
            db, tenant_id, module_key, authority=enabled, teacher=enabled, student=enabled, by=by)

    @staticmethod
    async def set_all_org_pages(db, tenant_id, enabled: bool, by=None):
        for m in MODULES:
            if m.get("required") or m.get("admin_only"):
                continue
            await RBACService.set_tenant_module(
                db, tenant_id, m["module_key"], authority=enabled, teacher=enabled, student=enabled, by=by)

    @staticmethod
    async def set_role_modules(db, role, module_keys: list[str], by=None):
        """Replace a role's granted modules with exactly `module_keys` (enabled).
        Used by the cross-section page-picker. Allow-list semantics: anything not
        listed is removed (= denied). Pages outside the org ceiling (locked/premium)
        and admin-only / non-staff-grantable pages are dropped — the admin can only
        assign what the org has and what a staff role can actually use."""
        candidate = {mk for mk in module_keys if get_module(mk)}
        valid = set()
        for mk in candidate:
            m = get_module(mk)
            if m.get("admin_only") or not m.get("staff_grantable", True):
                continue
            if not m.get("required") and not await RBACService.tenant_has_page(db, role.tenant_id, mk):
                continue  # org doesn't have this page → can't be granted
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
        """Replace which roles a holder of `role_id` may create users into.

        Candidates are validated: malformed UUIDs are dropped (avoids a DataError
        500), and only roles in the SAME tenant with user_type 'staff' are kept
        (avoids cross-tenant delegation and pointing at non-staff roles)."""
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
                    RbacRole.tenant_id == owner.tenant_id,
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

    # ---------------- tenant ceiling (tier-0, super-admin) ----------------
    @staticmethod
    async def get_tenant_permissions(db, tenant_id) -> list[dict]:
        tperm = {
            r.module_key: r for r in (await db.execute(
                select(TenantModulePermission).where(TenantModulePermission.tenant_id == tenant_id)
            )).scalars().all()
        }
        ttab = {
            (r.module_key, r.tab_key): r.enabled for r in (await db.execute(
                select(TenantTabPermission).where(TenantTabPermission.tenant_id == tenant_id)
            )).scalars().all()
        }
        out = []
        for m in MODULES:
            key = m["module_key"]
            tp = tperm.get(key)
            tabs = []
            for tk, tl in m["tabs"]:
                tabs.append({"tab_key": tk, "tab_label": tl, "enabled": ttab.get((key, tk), True)})
            out.append({
                "module_key": key, "module_name": m["module_name"], "icon": m["icon"],
                "path": m["path"], "audience": m["audience"], "premium": m["premium"],
                "authority_enabled": tp.authority_enabled if tp else (key not in PREMIUM_MODULE_KEYS),
                "teacher_enabled": tp.teacher_enabled if tp else (key not in PREMIUM_MODULE_KEYS),
                "student_enabled": tp.student_enabled if tp else (key not in PREMIUM_MODULE_KEYS),
                "tabs": tabs,
            })
        return out

    @staticmethod
    async def set_tenant_module(db, tenant_id, module_key, *, authority=None, teacher=None, student=None, by=None):
        row = (await db.execute(
            select(TenantModulePermission).where(
                TenantModulePermission.tenant_id == tenant_id,
                TenantModulePermission.module_key == module_key,
            )
        )).scalar_one_or_none()
        if not row:
            default = module_key not in PREMIUM_MODULE_KEYS
            row = TenantModulePermission(
                tenant_id=tenant_id, module_key=module_key,
                authority_enabled=default, teacher_enabled=default, student_enabled=default,
                configured_by=by,
            )
            db.add(row)
        if authority is not None:
            row.authority_enabled = authority
        if teacher is not None:
            row.teacher_enabled = teacher
        if student is not None:
            row.student_enabled = student
        if by:
            row.configured_by = by
        await db.commit()

    @staticmethod
    async def set_tenant_tab(db, tenant_id, module_key, tab_key, enabled: bool, by=None):
        row = (await db.execute(
            select(TenantTabPermission).where(
                TenantTabPermission.tenant_id == tenant_id,
                TenantTabPermission.module_key == module_key,
                TenantTabPermission.tab_key == tab_key,
            )
        )).scalar_one_or_none()
        if row:
            row.enabled = enabled
        else:
            db.add(TenantTabPermission(tenant_id=tenant_id, module_key=module_key, tab_key=tab_key, enabled=enabled, configured_by=by))
        await db.commit()
