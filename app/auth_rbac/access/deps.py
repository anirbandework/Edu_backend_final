"""Enforcement: require_module_access(module_key) dependency + role resolution."""
from __future__ import annotations
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ..security.deps import get_current_principal
from ..security.principal import Principal
from .service import RBACService

_IDENTITY_TABLE = {
    "school_authority": "school_authorities",
    "teacher": "teachers",
    "student": "students",
    "staff": "members",
}


async def resolve_role_id(db: AsyncSession, user_type: str, user_id) -> Optional[str]:
    """The caller's assigned rbac_role_id (or None). Read directly from the
    identity table to reflect role changes immediately."""
    tbl = _IDENTITY_TABLE.get(user_type)
    if not tbl or not user_id:
        return None
    try:
        row = (await db.execute(text(f"SELECT rbac_role_id FROM {tbl} WHERE id = :id"), {"id": str(user_id)})).first()
    except Exception:
        return None
    return str(row[0]) if row and row[0] else None


async def principal_has_module(db: AsyncSession, principal: Principal, module_key: str) -> bool:
    """True iff `principal` is a dynamic-staff user whose role grants `module_key`
    (explicit allow-list). Non-staff roles always return False here — their access
    is decided by the coarse role gate they pair this with."""
    if principal.role != "staff":
        return False
    role_id = await resolve_role_id(db, "staff", principal.user_id)
    if not role_id:
        return False
    return await RBACService.has_module_access(
        db, user_type="staff", tenant_id=principal.tenant_uuid,
        role_id=role_id, module_key=module_key,
    )


async def authority_admin_allowed(db: AsyncSession, principal: Principal, module_keys) -> bool:
    """For a school_authority (admin) caller: True iff their ADMIN ceiling
    (admin_enabled) grants at least one of `module_keys` for their tenant. Required
    pages bypass; no keys => allowed (not a page-specific route). Default-ON, so
    this only ever denies a page the super-admin EXPLICITLY revoked for this org."""
    if not module_keys:
        return True
    for k in module_keys:
        if await RBACService.tenant_admin_has_page(db, principal.tenant_uuid, k):
            return True
    return False


def require_authority_or_module(*module_keys: str):
    """ADDITIVE gate. Passes for the school admin / super-admin exactly as
    `require_authority` did, PLUS a dynamic-staff user whose role grants any of
    `module_keys`. The admin is additionally clamped by their 'Admin pages' ceiling
    (admin_enabled) — a super-admin can turn a page off for an org's admin. Non-staff
    (teacher/student) behaviour is unchanged — still denied here."""
    async def _dep(
        principal: Principal = Depends(get_current_principal),
        db: AsyncSession = Depends(get_db),
    ) -> Principal:
        if principal.is_super_admin:
            return principal
        if principal.is_authority:
            if await authority_admin_allowed(db, principal, module_keys):
                return principal
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This page is turned off for your account by the platform admin.",
            )
        for k in module_keys:
            if await principal_has_module(db, principal, k):
                return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this resource.",
        )
    return _dep


def require_staff_or_module(*module_keys: str):
    """ADDITIVE gate. Passes for admin / teacher / super-admin exactly as
    `require_staff` did, PLUS a dynamic-staff user whose role grants any of
    `module_keys`. The admin is additionally clamped by their 'Admin pages' ceiling."""
    async def _dep(
        principal: Principal = Depends(get_current_principal),
        db: AsyncSession = Depends(get_db),
    ) -> Principal:
        if principal.is_super_admin or principal.role == "teacher":
            return principal
        if principal.role == "school_authority":
            if await authority_admin_allowed(db, principal, module_keys):
                return principal
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This page is turned off for your account by the platform admin.",
            )
        for k in module_keys:
            if await principal_has_module(db, principal, k):
                return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this resource.",
        )
    return _dep


def require_module_access(module_key: str):
    """Router/route dependency: 403 unless the caller's role (intersected with the
    tenant ceiling) grants this module. Super-admin bypasses."""
    async def _checker(
        principal: Principal = Depends(get_current_principal),
        db: AsyncSession = Depends(get_db),
    ) -> Principal:
        if principal.is_super_admin:
            return principal
        role_id = await resolve_role_id(db, principal.role, principal.user_id)
        allowed = await RBACService.has_module_access(
            db,
            user_type=principal.role,
            tenant_id=principal.tenant_uuid,
            role_id=role_id,
            module_key=module_key,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role does not have access to '{module_key}'.",
            )
        return principal
    return _checker
