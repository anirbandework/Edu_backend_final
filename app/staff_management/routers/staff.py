"""Staff & Users API — the unified, dynamic-role user directory for a school.

Create/list/manage members. Creation is delegation-gated: an admin may add
any role in their school; a staff member may add only the roles their own role
was granted permission to create.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.service import RBACService
from ...auth_rbac.access.deps import resolve_role_id
from ..services.staff_service import StaffService

router = APIRouter(prefix="/api/staff", tags=["Staff & Users"])


class StaffCreate(BaseModel):
    first_name: str
    last_name: str
    phone: str
    rbac_role_id: str
    email: Optional[str] = None
    position: Optional[str] = None


class StaffUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    position: Optional[str] = None
    rbac_role_id: Optional[str] = None


class StatusBody(BaseModel):
    is_active: bool


class PasswordBody(BaseModel):
    password: str


def _tenant(principal: Principal) -> str:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="No active school in session.")
    return principal.tenant_id


async def _require_manage_staff(db, principal: Principal) -> None:
    """Authorize callers who may view/manage the staff directory. The /api/staff
    router is otherwise only AUTHED, so without this ANY tenant user (student,
    teacher, zero-permission staff) could read/edit/delete staff. Allowed:
    the school admin, the super-admin, or a staff user whose role was granted
    the 'Staff & Users' (staff) page."""
    _tenant(principal)
    if principal.is_authority or principal.is_super_admin:
        return
    if principal.role == "staff":
        role_id = await resolve_role_id(db, "staff", principal.user_id)
        if role_id and await RBACService.has_module_access(
            db, user_type="staff", tenant_id=principal.tenant_uuid,
            role_id=role_id, module_key="staff",
        ):
            return
    raise HTTPException(status_code=403, detail="You are not allowed to manage staff.")


async def _load(db, principal, staff_id):
    staff = await StaffService.get(db, staff_id, _tenant(principal))
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found.")
    return staff


async def _validate_role(db, principal, role_id: str):
    role = await RBACService.get_role(db, role_id)
    if not role or str(role.tenant_id) != str(principal.tenant_id):
        raise HTTPException(status_code=400, detail="Invalid role for this school.")
    # A members account may only carry a dynamic 'staff' role — never a
    # teacher/student/authority role (which would smuggle that audience's pages).
    if role.user_type != "staff":
        raise HTTPException(status_code=400, detail="That role cannot be assigned to a staff member.")
    if not await StaffService.can_principal_create_role(db, principal, role_id):
        raise HTTPException(status_code=403, detail="You are not allowed to assign that role.")
    return role


@router.get("")
async def list_staff(principal: Principal = Depends(get_current_principal),
                     db: AsyncSession = Depends(get_db)):
    await _require_manage_staff(db, principal)
    return await StaffService.list_staff(db, _tenant(principal))


@router.post("")
async def create_staff(body: StaffCreate,
                       principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    await _require_manage_staff(db, principal)
    await _validate_role(db, principal, body.rbac_role_id)
    try:
        staff = await StaffService.create(
            db, tenant_id=principal.tenant_uuid, rbac_role_id=body.rbac_role_id,
            first_name=body.first_name, last_name=body.last_name, phone=body.phone,
            email=body.email, position=body.position,
            created_by=principal.user_uuid,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # No password, no invite. The user sets their own password at first login
    # (phone + OTP, see /api/auth/signup/*).
    return {
        "id": str(staff.id), "staff_id": staff.staff_id,
        "name": f"{staff.first_name} {staff.last_name}".strip(),
        "login_enabled": False,
    }


@router.put("/{staff_id}")
async def update_staff(staff_id: str, body: StaffUpdate,
                       principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    await _require_manage_staff(db, principal)
    staff = await _load(db, principal, staff_id)
    if body.rbac_role_id is not None and body.rbac_role_id:
        await _validate_role(db, principal, body.rbac_role_id)
    try:
        staff = await StaffService.update(
            db, staff, first_name=body.first_name, last_name=body.last_name,
            email=body.email, phone=body.phone, position=body.position,
            rbac_role_id=body.rbac_role_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(staff.id), "detail": "updated"}


@router.patch("/{staff_id}/status")
async def set_status(staff_id: str, body: StatusBody,
                     principal: Principal = Depends(get_current_principal),
                     db: AsyncSession = Depends(get_db)):
    await _require_manage_staff(db, principal)
    staff = await _load(db, principal, staff_id)
    await StaffService.set_status(db, staff, body.is_active)
    return {"id": staff_id, "status": "active" if body.is_active else "inactive"}


@router.post("/{staff_id}/reset-password")
async def reset_password(staff_id: str, body: PasswordBody,
                         principal: Principal = Depends(get_current_principal),
                         db: AsyncSession = Depends(get_db)):
    await _require_manage_staff(db, principal)
    staff = await _load(db, principal, staff_id)
    try:
        await StaffService.reset_password(db, staff, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": staff_id, "detail": "password reset"}


# Deleting users is intentionally NOT supported — it orphans their enrolments/marks/etc.
# Use PATCH /{staff_id}/status to DEACTIVATE instead (keeps the record + history intact).
