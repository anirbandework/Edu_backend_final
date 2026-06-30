"""Staff & Users API — the unified, dynamic-role user directory for an organisation.

Create/list/manage members. Page-access model: an admin may add any role in their
organisation; a staff member who holds the "Staff & Users" page may add users into ANY
of the organisation's roles. Holding the page IS the grant to manage users — there is no
separate per-role delegation step.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.service import RBACService
from ...auth_rbac.access import custom_fields as cf
from ...auth_rbac.access.deps import resolve_role_id
from ..services.staff_service import StaffService
from ..services import imports

router = APIRouter(prefix="/api/staff", tags=["Staff & Users"])


class StaffCreate(BaseModel):
    first_name: str
    last_name: str
    phone: str
    rbac_role_id: str
    email: Optional[str] = None
    position: Optional[str] = None
    custom_fields: Optional[dict] = None  # {field_key: value} for the role's defined fields


class StaffUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    position: Optional[str] = None
    rbac_role_id: Optional[str] = None
    custom_fields: Optional[dict] = None


class StatusBody(BaseModel):
    is_active: bool


class PasswordBody(BaseModel):
    password: str


def _organisation(principal: Principal) -> str:
    if not principal.organisation_id:
        raise HTTPException(status_code=400, detail="No active organisation in session.")
    return principal.organisation_id


async def _require_manage_staff(db, principal: Principal) -> None:
    """Authorize callers who may view/manage the staff directory. The /api/staff
    router is otherwise only AUTHED, so without this ANY organisation user (student,
    teacher, zero-permission staff) could read/edit/delete staff. Allowed:
    the organisation admin, the super-admin, or a staff user whose role was granted
    the 'Staff & Users' (staff) page."""
    _organisation(principal)
    if principal.is_authority or principal.is_super_admin:
        return
    if principal.role == "staff":
        role_id = await resolve_role_id(db, "staff", principal.user_id)
        if role_id and await RBACService.has_module_access(
            db, user_type="staff", organisation_id=principal.organisation_uuid,
            role_id=role_id, module_key="staff",
        ):
            return
    raise HTTPException(status_code=403, detail="You are not allowed to manage staff.")


async def _load(db, principal, staff_id):
    staff = await StaffService.get(db, staff_id, _organisation(principal))
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found.")
    return staff


async def _validate_role(db, principal, role_id: str):
    role = await RBACService.get_role(db, role_id)
    if not role or str(role.organisation_id) != str(principal.organisation_id):
        raise HTTPException(status_code=400, detail="Invalid role for this organisation.")
    # A members account may only carry a dynamic 'staff' role — never a
    # teacher/student/authority role (which would smuggle that audience's pages).
    if role.user_type != "staff":
        raise HTTPException(status_code=400, detail="That role cannot be assigned to a staff member.")
    if not await StaffService.can_principal_create_role(db, principal, role_id):
        raise HTTPException(status_code=403, detail="You are not allowed to assign that role.")
    return role


@router.get("")
async def list_staff(limit: int = 100, offset: int = 0, q: str = "", role_id: str = "",
                     principal: Principal = Depends(get_current_principal),
                     db: AsyncSession = Depends(get_db)):
    await _require_manage_staff(db, principal)
    if role_id:
        # The role filter must be one of the caller's OWN org roles — never leak
        # whether a foreign org's role id exists (cross-org enumeration oracle).
        r = await RBACService.get_role(db, role_id)
        if not r or str(r.organisation_id) != str(principal.organisation_id):
            raise HTTPException(status_code=400, detail="Invalid role filter.")
    limit = max(1, min(int(limit or 100), 200))  # capped page size
    offset = max(0, int(offset or 0))
    return await StaffService.list_staff(
        db, _organisation(principal), limit=limit, offset=offset, q=q, role_id=role_id or None)


@router.get("/{staff_id}")
async def get_staff(staff_id: str, principal: Principal = Depends(get_current_principal),
                    db: AsyncSession = Depends(get_db)):
    """One member's full record INCLUDING custom-field values — fetched on demand by the
    details view, so the list payload stays lean (and PII off the wire) at scale."""
    await _require_manage_staff(db, principal)
    staff = await _load(db, principal, staff_id)
    role_names = {}
    if staff.rbac_role_id:
        role = await RBACService.get_role(db, staff.rbac_role_id)
        if role:
            role_names[str(staff.rbac_role_id)] = role.role_name
    return StaffService._serialize(staff, role_names, include_custom=True)


# ----------------------------- bulk import (Excel / CSV) -----------------------------
@router.get("/import/template")
async def import_template(role_id: str, principal: Principal = Depends(get_current_principal),
                          db: AsyncSession = Depends(get_db)):
    """Download an .xlsx template whose columns are the built-in fields + the role's
    custom fields (dropdowns for select fields)."""
    await _require_manage_staff(db, principal)
    role = await _validate_role(db, principal, role_id)
    data = imports.build_template_xlsx(role)
    fname = (role.role_name or "role").strip().replace(" ", "_") + "_template.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/import")
async def import_users(file: UploadFile = File(...), role_id: str = Form(...),
                       principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    """Bulk-create members of `role_id` from an uploaded .xlsx/.csv. Imports the valid
    rows and returns a per-row report of failures + skipped (duplicate) rows."""
    await _require_manage_staff(db, principal)
    role = await _validate_role(db, principal, role_id)
    content = await file.read()
    if len(content) > imports.MAX_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"File too large (max {imports.MAX_BYTES // (1024 * 1024)} MB).")
    rows, err = imports.parse_rows(file.filename or "", content, role)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if not rows:
        raise HTTPException(status_code=400, detail="No data rows found in the file.")
    if len(rows) > imports.MAX_ROWS:
        raise HTTPException(status_code=400,
                            detail=f"Too many rows ({len(rows)}). Max {imports.MAX_ROWS} per "
                                   "upload — split the file and upload in parts.")
    return await imports.bulk_import(
        db, organisation_id=principal.organisation_uuid, role=role,
        rows=rows, created_by=principal.user_uuid)


@router.post("")
async def create_staff(body: StaffCreate,
                       principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    await _require_manage_staff(db, principal)
    role = await _validate_role(db, principal, body.rbac_role_id)
    try:
        clean_custom = cf.validate_values(role.custom_fields or [], body.custom_fields or {})
        staff = await StaffService.create(
            db, organisation_id=principal.organisation_uuid, rbac_role_id=body.rbac_role_id,
            first_name=body.first_name, last_name=body.last_name, phone=body.phone,
            email=body.email, position=body.position,
            created_by=principal.user_uuid, custom_values=clean_custom,
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
    effective_role = None
    if body.rbac_role_id is not None and body.rbac_role_id:
        effective_role = await _validate_role(db, principal, body.rbac_role_id)
    try:
        # Validate custom values against the EFFECTIVE role (new role if changing, else current).
        clean_custom = None
        if body.custom_fields is not None:
            role = effective_role or await RBACService.get_role(db, staff.rbac_role_id)
            clean_custom = cf.validate_values((role.custom_fields if role else []) or [], body.custom_fields)
        staff = await StaffService.update(
            db, staff, first_name=body.first_name, last_name=body.last_name,
            email=body.email, phone=body.phone, position=body.position,
            rbac_role_id=body.rbac_role_id, custom_values=clean_custom,
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
    try:
        await StaffService.set_status(db, staff, body.is_active)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
