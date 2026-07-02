"""Authentication endpoints.

Onboarding is password-less first-login (phone + OTP) — there is NO invite/link system.
Public:   login (phone+password), refresh, signup (phone+OTP first-login), forgot-password (OTP),
          public organisation list.
Authed:   logout, me, profile, change-password; super-admin: groups, admins, module-access,
          organisation status; admin: my-organisations, switch/create organisation.
"""
from __future__ import annotations
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from sqlalchemy import select, text

from sqlalchemy.exc import IntegrityError

from ...core.database import get_db
from ...core.rate_limit import rate_limiter
from ...core.config import settings
from ..services.auth_service import AuthService
from ..services import login_service, phone_service, signup_service
from ...authority_management.models.authority import Authority
from ...organisation_management.services.organisation_service import OrganisationService
from ...organisation_management.schemas.organisation_schemas import OrganisationCreate, OrganisationUpdate
from ..security import otp
from ..security.tokens import (
    create_access_token, create_refresh_token, decode_token, TokenError, REFRESH,
)
from ..security.password import hash_password_async, verify_password_async
from ..security.sessions import sessions_invalid_before, invalidate_sessions
from ..security.principal import Principal
from ..security.deps import get_current_principal, require_super_admin, require_authority

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
_bearer = HTTPBearer(auto_error=False)

MIN_PASSWORD_LEN = 6


# ----------------------------- schemas -----------------------------
class LoginRequest(BaseModel):
    phone: str = Field(..., description="Phone number (super-admin uses its email here)")
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    organisation_id: Optional[str] = None
    group_id: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class SignupOtpRequest(BaseModel):
    phone: str


class OtpSentResponse(BaseModel):
    sent: bool
    dev_code: Optional[str] = None  # only populated in dev mode


class SignupVerifyRequest(BaseModel):
    phone: str
    otp: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _pw_len(cls, v: str) -> str:
        if not v or len(v) < MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        return v


class ForgotOtpRequest(BaseModel):
    phone: str


class ResetPasswordRequest(BaseModel):
    phone: str
    otp: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw_len(cls, v: str) -> str:
        if not v or len(v) < MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        return v


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


# ----------------------------- login / token -----------------------------
@router.post("/login", response_model=TokenResponse,
             dependencies=[Depends(rate_limiter("login", 10, 60))])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        identity = await login_service.authenticate(db, identifier=body.phone, password=body.password)
    except login_service.AccountInactiveError as e:
        # Credentials were valid, but the account / organisation / institution group
        # is deactivated — surface the specific reason.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    if not identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or password")
    return TokenResponse(
        access_token=create_access_token(user_id=identity.user_id, role=identity.role, organisation_id=identity.organisation_id, group_id=identity.group_id),
        refresh_token=create_refresh_token(user_id=identity.user_id, role=identity.role, organisation_id=identity.organisation_id, group_id=identity.group_id),
        user_id=identity.user_id, role=identity.role, organisation_id=identity.organisation_id, group_id=identity.group_id,
    )


@router.get("/organisations")
async def list_organisations(
    q: str = "",
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Public: minimal organisation list for the login picker (no sensitive fields).

    SEARCH-DRIVEN + CAPPED so it scales to 100k+ organisations (never loads them all —
    that was an unauthenticated OOM/DoS). `q` filters by name or code (server-side,
    indexed-friendly ILIKE); `limit` is clamped to 1..50. With no `q`, returns the
    first `limit` orgs by name (fine for small deployments; large ones type to search).

    Deactivated organisations are INCLUDED but flagged `is_active=false` so the picker
    greys them out (and an org whose institution GROUP is deactivated reads inactive too)."""
    limit = max(1, min(int(limit or 20), 50))
    term = (q or "").strip()
    where = "WHERE o.is_deleted = false"
    params = {"limit": limit}
    if term:
        where += " AND (o.name ILIKE :q OR o.code ILIKE :q)"
        params["q"] = f"%{term}%"  # bound as a value — not string-interpolated SQL
    rows = (await db.execute(text(
        f"SELECT o.id, o.name, o.code, o.address, o.org_type, o.is_active, o.group_id "
        f"FROM organisations o {where} ORDER BY o.name LIMIT :limit"
    ), params)).mappings().all()
    # Only INACTIVE groups (a small set) → every org under them reads as inactive.
    inactive_groups = {str(r[0]) for r in (await db.execute(text(
        "SELECT id FROM institution_groups WHERE is_active = false OR is_deleted = true"
    ))).all()}

    def _effective_active(r) -> bool:
        if not r["is_active"]:
            return False
        gid = str(r["group_id"]) if r["group_id"] else None
        return gid not in inactive_groups

    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "code": r["code"],
            "address": r["address"],
            "org_type": r["org_type"],
            "total_students": 0,
            "total_teachers": 0,
            "is_active": _effective_active(r),
        }
        for r in rows
    ]


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, expected_type=REFRESH)
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    # Honour deactivation for live sessions: refreshing fails once the caller's
    # organisation or institution group has been deactivated (the super-admin is exempt).
    role = payload.get("role", "")
    # Session revocation: a refresh token issued before the user's sessions were
    # invalidated (password change/reset) can no longer mint access tokens.
    iat = payload.get("iat")
    if iat is not None:
        invalid_before = await sessions_invalid_before(db, role, payload["sub"])
        if invalid_before and float(iat) < invalid_before:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Session expired — please log in again.")
    if role != "super_admin":
        try:
            await login_service.assert_active(
                db, role=role,
                organisation_id=payload.get("organisation_id"),
                group_id=payload.get("group_id"),
            )
        except login_service.AccountInactiveError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    return TokenResponse(
        access_token=create_access_token(user_id=payload["sub"], role=payload.get("role", ""), organisation_id=payload.get("organisation_id"), group_id=payload.get("group_id")),
        refresh_token=body.refresh_token,
        user_id=payload["sub"], role=payload.get("role", ""), organisation_id=payload.get("organisation_id"), group_id=payload.get("group_id"),
    )


@router.post("/logout")
async def logout(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if creds and creds.credentials:
        try:
            payload = decode_token(creds.credentials)
            jti = payload.get("jti")
            ttl = max(1, int(payload.get("exp", 0)) - int(time.time()))
            if jti:
                from ...core.cache import cache_service
                await cache_service.set(f"denylist:{jti}", "1", ttl=ttl)
        except Exception:
            pass
    return {"detail": "logged out"}


@router.get("/me")
async def me(principal: Principal = Depends(get_current_principal)):
    return {"user_id": principal.user_id, "role": principal.role, "organisation_id": principal.organisation_id}


@router.get("/profile")
async def my_profile(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """The authenticated caller's own identity profile (every role). Always
    available — not gated by page permissions."""
    profile = await AuthService.get_user_profile(db, principal.user_uuid, None)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _len(cls, v: str) -> str:
        if not v or len(v) < MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
        return v


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Change one's own password: verify the current password, then set the new
    one. Works for every role (super-admin/admin/staff/teacher/student)."""
    user = await AuthService.get_identity_record(db, principal.role, principal.user_uuid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not getattr(user, "password_hash", None) or not await verify_password_async(
        body.current_password, user.password_hash
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = await hash_password_async(body.new_password)
    # Kill every other session the user had (access + refresh) — a password change
    # must log out any compromised session.
    await invalidate_sessions(db, principal.role, principal.user_id)
    await db.commit()
    return {"detail": "Password changed successfully"}


# NOTE: there is NO invite system. The super-admin creates admins via POST /admins and
# the admin creates staff via POST /api/staff — both password-less. Each user then sets
# their OWN password at first login (phone + OTP, see /signup/*). Teacher/Student are not
# roles; every non-admin is a dynamic `staff` member with an assigned rbac_role.


# ----------------------------- super-admin: ADMINS -----------------------------
# Login is by phone + password, so both are compulsory; email is optional.
class CreateAdminRequest(BaseModel):
    first_name: str
    last_name: str
    phone: str
    email: Optional[str] = None
    group_id: str  # the institution group this admin belongs to
    modules: list[str] = Field(default_factory=list)  # (legacy; admin pages now per-group)


class UpdateAdminRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class UpdateAdminModulesRequest(BaseModel):
    modules: list[str]


class AdminStatusRequest(BaseModel):
    is_active: bool


class AdminResetPasswordRequest(BaseModel):
    password: str


def _admin_modules(permissions) -> list:
    if isinstance(permissions, str):
        import json as _json
        try:
            permissions = _json.loads(permissions)
        except Exception:
            permissions = {}
    if isinstance(permissions, dict):
        mods = permissions.get("modules")
        return mods if isinstance(mods, list) else []
    return []


def _admin_dict(sa: Authority, org_count: int = 0) -> dict:
    return {
        "id": str(sa.id),
        "first_name": sa.first_name,
        "last_name": sa.last_name,
        "email": sa.email,
        "phone": sa.phone,
        "status": sa.status,
        "modules": _admin_modules(sa.permissions),
        "org_count": org_count,
    }


@router.post("/admins")
async def create_admin(
    body: CreateAdminRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Super-admin creates an ADMIN (authority) with NO organisation yet, the
    pages they may use, and a phone+password they log in with immediately. Email
    is optional; the admin creates their organisation(s) after first login."""
    if not body.phone.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone is required.")
    await phone_service.assert_phone_available(db, body.phone)

    # Create the admin password-less (status='invited'); the granted pages are stored
    # now. They set their own password at first login (phone + OTP) — no link needed.
    user = await signup_service.create_invited_user(
        db, role="authority", organisation_id=None,
        first_name=body.first_name, last_name=body.last_name,
        email=(body.email.strip() or None) if body.email else None, phone=body.phone.strip(),
        extra={"group_id": body.group_id, "permissions": {"modules": body.modules}},
    )
    await db.refresh(user)
    # No invite. The admin sets their own password at first login (phone + OTP).
    return {**_admin_dict(user), "message": "Admin created"}


@router.get("/admins")
async def list_admins(
    group_id: Optional[str] = None,
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Admins (paginated + searchable) with their institution group, the group's
    organisation count, granted modules + status. Optional ?group_id=… filters to one
    group; `q` matches name/phone/email. Envelope {items,total,limit,offset}."""
    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    where = "a.is_deleted = false AND a.role = 'authority'"
    params: dict = {"limit": limit, "offset": offset}
    if group_id:
        where += " AND a.group_id = :gid"
        params["gid"] = group_id
    term = (q or "").strip()
    if term:
        where += (" AND (a.first_name ILIKE :q OR a.last_name ILIKE :q "
                  "OR a.email ILIKE :q OR a.phone ILIKE :q)")
        params["q"] = f"%{term}%"
    total = (await db.execute(text(
        f"SELECT COUNT(*) FROM authorities a WHERE {where}"  # noqa: S608 (static fragments + bound params)
    ), params)).scalar() or 0
    rows = (await db.execute(text(
        f"""
        SELECT a.id, a.first_name, a.last_name, a.email, a.phone, a.status, a.permissions,
               a.group_id, g.name AS group_name,
               (SELECT COUNT(*) FROM organisations t
                 WHERE t.group_id = a.group_id AND t.is_deleted = false) AS org_count
        FROM authorities a
        LEFT JOIN institution_groups g ON g.id = a.group_id
        WHERE {where}
        ORDER BY a.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    ), params)).mappings().all()
    return {
        "items": [{
            "id": str(r["id"]),
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "email": r["email"],
            "phone": r["phone"],
            "status": r["status"],
            "group_id": str(r["group_id"]) if r["group_id"] else None,
            "group_name": r["group_name"],
            "modules": _admin_modules(r["permissions"]),
            "org_count": int(r["org_count"] or 0),
        } for r in rows],
        "total": int(total), "limit": limit, "offset": offset,
    }


@router.put("/admins/{admin_id}/modules")
async def update_admin_modules(
    admin_id: UUID,
    body: UpdateAdminModulesRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Set which modules/pages an admin (and all their organisations) may use."""
    sa = (await db.execute(select(Authority).where(Authority.id == admin_id))).scalar_one_or_none()
    if not sa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
    perms = dict(sa.permissions) if isinstance(sa.permissions, dict) else {}
    perms["modules"] = body.modules
    sa.permissions = perms
    await db.commit()
    return {"id": str(admin_id), "modules": body.modules, "message": "Modules updated"}


async def _load_admin(db: AsyncSession, admin_id: UUID) -> Authority:
    sa = (await db.execute(
        select(Authority).where(
            Authority.id == admin_id, Authority.is_deleted == False
        )
    )).scalar_one_or_none()
    if not sa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
    return sa


@router.put("/admins/{admin_id}")
async def update_admin(
    admin_id: UUID,
    body: UpdateAdminRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Edit an admin's name / phone / email."""
    sa = await _load_admin(db, admin_id)
    if body.phone is not None and body.phone.strip() and body.phone.strip() != sa.phone:
        await phone_service.assert_phone_available(db, body.phone, exclude_user_id=str(sa.id))
        sa.phone = body.phone.strip()
    if body.first_name is not None:
        sa.first_name = body.first_name.strip()
    if body.last_name is not None:
        sa.last_name = body.last_name.strip()
    if body.email is not None:
        sa.email = body.email.strip() or None
    await db.commit()
    await db.refresh(sa)
    return {**_admin_dict(sa), "message": "Admin updated"}


@router.patch("/admins/{admin_id}/status")
async def set_admin_status(
    admin_id: UUID,
    body: AdminStatusRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Activate / deactivate an admin (a deactivated admin cannot log in)."""
    sa = await _load_admin(db, admin_id)
    sa.status = "active" if body.is_active else "inactive"
    await db.commit()
    return {"id": str(admin_id), "status": sa.status,
            "message": "Admin activated" if body.is_active else "Admin deactivated"}


@router.post("/admins/{admin_id}/reset-password")
async def reset_admin_password(
    admin_id: UUID,
    body: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Set a new password for an admin (login is phone+password)."""
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    sa = await _load_admin(db, admin_id)
    sa.password_hash = await hash_password_async(body.password)
    await invalidate_sessions(db, "authority", admin_id)  # log out the admin's old sessions
    await db.commit()
    return {"id": str(admin_id), "message": "Password reset"}


# Admins are never hard-deleted — only deactivated (PATCH /admins/{id}/status). A
# deactivated admin cannot log in; their data and organisations are preserved.


# ----------------------------- super-admin: INSTITUTION GROUPS -----------------------------
class CreateGroupRequest(BaseModel):
    name: str


@router.post("/groups")
async def create_group(
    body: CreateGroupRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Create an institution group (the top-level grouping above organisations).
    The super-admin then creates admins into it and sets its module-access ceilings."""
    import re as _re, uuid as _uuid
    from ...group_management.models.group import InstitutionGroup
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group name is required.")
    letters = (_re.sub(r"[^A-Za-z]", "", name).upper()[:3]) or "GRP"
    code = f"{letters}{_uuid.uuid4().hex[:6].upper()}"
    grp = InstitutionGroup(name=name, code=code)
    db.add(grp)
    await db.commit()
    await db.refresh(grp)
    return {"id": str(grp.id), "name": grp.name, "code": grp.code,
            "is_active": grp.is_active, "admin_count": 0, "org_count": 0,
            "message": "Group created"}


@router.get("/groups")
async def list_groups(
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Institution groups (paginated + searchable) with admin + organisation counts.
    Envelope {items,total,limit,offset}; `q` matches name or code."""
    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    where = "g.is_deleted = false"
    params: dict = {"limit": limit, "offset": offset}
    term = (q or "").strip()
    if term:
        where += " AND (g.name ILIKE :q OR g.code ILIKE :q)"
        params["q"] = f"%{term}%"
    total = (await db.execute(text(
        f"SELECT COUNT(*) FROM institution_groups g WHERE {where}"  # noqa: S608 (static fragments + bound :q)
    ), params)).scalar() or 0
    rows = (await db.execute(text(
        f"""
        SELECT g.id, g.name, g.code, g.is_active,
               (SELECT COUNT(*) FROM authorities a
                  WHERE a.group_id = g.id AND a.is_deleted = false AND a.role = 'authority') AS admin_count,
               (SELECT COUNT(*) FROM organisations o
                  WHERE o.group_id = g.id AND o.is_deleted = false) AS org_count
        FROM institution_groups g
        WHERE {where}
        ORDER BY g.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    ), params)).mappings().all()
    return {
        "items": [{
            "id": str(r["id"]), "name": r["name"], "code": r["code"], "is_active": r["is_active"],
            "admin_count": int(r["admin_count"] or 0), "org_count": int(r["org_count"] or 0),
        } for r in rows],
        "total": int(total), "limit": limit, "offset": offset,
    }


@router.get("/groups/{group_id}/organisations")
async def group_organisations(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """All organisations in a group (for the super-admin's group drill-down)."""
    rows = (await db.execute(text(
        "SELECT id, name, code, org_type, is_active FROM organisations "
        "WHERE group_id = :gid AND is_deleted = false ORDER BY created_at DESC"
    ), {"gid": str(group_id)})).mappings().all()
    return [{"id": str(r["id"]), "name": r["name"], "code": r["code"],
             "org_type": r["org_type"], "is_active": r["is_active"]} for r in rows]


@router.patch("/groups/{group_id}/status")
async def set_group_status(
    group_id: UUID,
    body: AdminStatusRequest,  # {is_active: bool}
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Activate / deactivate a whole institution group. When deactivated, NOBODY in
    the group can log in — neither its admins (group_id on the token) nor any staff in
    any of its organisations (resolved org → group at login)."""
    res = await db.execute(text(
        "UPDATE institution_groups SET is_active = :a WHERE id = :id AND is_deleted = false"
    ), {"a": bool(body.is_active), "id": str(group_id)})
    await db.commit()
    if not res.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return {"id": str(group_id), "is_active": bool(body.is_active),
            "message": "Group activated" if body.is_active else "Group deactivated"}


@router.patch("/organisations/{organisation_id}/status")
async def set_organisation_status(
    organisation_id: UUID,
    body: AdminStatusRequest,  # {is_active: bool}
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Activate / deactivate a single organisation. When deactivated, that org's
    staff/users cannot log in. Admins are group-level, so they are not blocked — they
    can still switch to the org (e.g. to reactivate it)."""
    res = await db.execute(text(
        "UPDATE organisations SET is_active = :a WHERE id = :id AND is_deleted = false"
    ), {"a": bool(body.is_active), "id": str(organisation_id)})
    await db.commit()
    if not res.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    return {"id": str(organisation_id), "is_active": bool(body.is_active),
            "message": "Organisation activated" if body.is_active else "Organisation deactivated"}


# ----------------------------- admin: ORGANISATION SWITCHER -----------------------------
@router.get("/my-organisations")
async def my_organisations(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """All organisations in the admin's institution GROUP (every admin of the group
    sees them all). Feeds the active-organisation switcher."""
    rows = (await db.execute(text(
        """
        SELECT id, name, code, is_active
        FROM organisations
        WHERE group_id = :gid AND is_deleted = false
        ORDER BY created_at DESC
        """
    ), {"gid": str(principal.group_id) if principal.group_id else None})).mappings().all()
    return [{"id": str(r["id"]), "name": r["name"],
             "code": r["code"], "is_active": r["is_active"]} for r in rows]


@router.post("/switch-organisation/{organisation_id}", response_model=TokenResponse)
async def switch_organisation(
    organisation_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """Re-scope the admin's session to one of their GROUP's organisations (new JWT)."""
    in_group = (await db.execute(text(
        "SELECT 1 FROM organisations WHERE id = :tid AND group_id = :gid "
        "AND is_deleted = false LIMIT 1"
    ), {"tid": str(organisation_id), "gid": str(principal.group_id) if principal.group_id else None})).first()
    if not in_group:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This organisation is not in your group")
    # Remember it as the admin's active organisation.
    await db.execute(text(
        "UPDATE authorities SET organisation_id = :tid WHERE id = :oid"
    ), {"tid": str(organisation_id), "oid": str(principal.user_id)})
    await db.commit()
    tid = str(organisation_id)
    return TokenResponse(
        access_token=create_access_token(user_id=str(principal.user_id), role=principal.role, organisation_id=tid, group_id=principal.group_id),
        refresh_token=create_refresh_token(user_id=str(principal.user_id), role=principal.role, organisation_id=tid, group_id=principal.group_id),
        user_id=str(principal.user_id), role=principal.role, organisation_id=tid, group_id=principal.group_id,
    )


@router.post("/organisations")
async def create_my_organisation(
    body: OrganisationCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """An ADMIN creates a organisation they own. (The /api/v1/organisations router is
    super-admin-only; this is the admin's self-service create.) The new organisation is
    stamped with owner_authority_id = the admin and becomes their active organisation
    if they had none."""
    service = OrganisationService(db)
    organisation_dict = body.model_dump()
    if not organisation_dict.get("code"):
        organisation_dict["code"] = await service.generate_code(organisation_dict["name"])
    try:
        organisation = await service.create(organisation_dict)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="An organisation with these details already exists.")
    if not organisation:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Organisation creation failed")
    # Stamp the new organisation with the admin's GROUP (visible to all the group's
    # admins) + record who created it. Make it the admin's active org if they had none.
    await db.execute(text(
        "UPDATE organisations SET owner_authority_id = :oid, group_id = :gid WHERE id = :tid"
    ), {"oid": str(principal.user_id),
        "gid": str(principal.group_id) if principal.group_id else None,
        "tid": str(organisation.id)})
    await db.execute(text(
        "UPDATE authorities SET organisation_id = :tid WHERE id = :oid AND organisation_id IS NULL"
    ), {"tid": str(organisation.id), "oid": str(principal.user_id)})
    await db.commit()
    # Seed the org_type's STARTER ROLES (Teacher/Student/Parent/... with capabilities +
    # a safe default) and attach the named head to the head role. All admin-editable.
    # Best-effort: a hiccup here never fails the org creation itself.
    seed = None
    try:
        from ..access.org_presets import seed_starter_roles
        seed = await seed_starter_roles(
            db, organisation_id=organisation.id,
            org_type=organisation_dict.get("org_type") or "School",
            created_by=principal.user_uuid,
            head_name=organisation_dict.get("head_name") or "",
        )
    except Exception as e:  # pragma: no cover - seeding must not break org creation
        import logging
        logging.getLogger(__name__).warning("starter-role seeding failed: %s", e)
    return {"id": str(organisation.id), "name": organisation.name,
            "code": organisation.code, "message": "Organisation created",
            "head": (seed or {}).get("head"), "seeded_roles": (seed or {}).get("roles")}


def _org_detail(o) -> dict:
    """Editable detail of an organisation for the admin's profile → Organisation tab."""
    return {
        "id": str(o.id),
        "name": o.name,
        "code": getattr(o, "code", None),
        "address": getattr(o, "address", None),
        "phone": getattr(o, "phone", None),
        "email": getattr(o, "email", None),
        "head_name": getattr(o, "head_name", None),
        "org_type": getattr(o, "org_type", None),
        "language_of_instruction": getattr(o, "language_of_instruction", None),
        "levels_offered": getattr(o, "levels_offered", None) or [],
        "established_year": getattr(o, "established_year", None),
        "accreditation": getattr(o, "accreditation", None),
        "maximum_capacity": getattr(o, "maximum_capacity", None),
        "annual_tuition": float(getattr(o, "annual_tuition", 0) or 0),
        "registration_fee": float(getattr(o, "registration_fee", 0) or 0),
        "is_active": getattr(o, "is_active", True),
    }


@router.get("/my-organisation")
async def get_my_organisation(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """Full detail of the admin's ACTIVE organisation (profile → Organisation tab)."""
    oid = principal.organisation_uuid
    if not oid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No active organisation yet — create one first.")
    org = await OrganisationService(db).get(oid)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    return _org_detail(org)


@router.patch("/my-organisation")
async def update_my_organisation(
    body: OrganisationUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """Update the admin's ACTIVE organisation. Always scoped to the admin's OWN active
    org (id from the token, never the client) and verified to be in their group."""
    oid = principal.organisation_uuid
    if not oid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active organisation.")
    in_group = (await db.execute(text(
        "SELECT 1 FROM organisations WHERE id = :tid AND group_id = :gid AND is_deleted = false LIMIT 1"
    ), {"tid": str(oid), "gid": str(principal.group_id) if principal.group_id else None})).first()
    if not in_group:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your organisation.")
    update_data = body.model_dump(exclude_unset=True)
    # An admin edits content here; activation/deactivation is the super-admin's control.
    update_data.pop("is_active", None)
    update_data.pop("code", None)  # code is system-generated, not admin-editable
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No changes provided.")
    try:
        org = await OrganisationService(db).update(oid, update_data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Those details conflict with another organisation (e.g. email).")
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    return _org_detail(org)


# ----------------------------- first-login signup (phone + OTP, NO invite) -----------------------------
# The admin creates the user (password-less). The user then sets their OWN password here:
# enter phone -> OTP -> password. There is no invite link or token anywhere.
@router.post("/signup/request-otp", response_model=OtpSentResponse,
             dependencies=[Depends(rate_limiter("signup_otp", 5, 300))])
async def signup_request_otp(body: SignupOtpRequest, db: AsyncSession = Depends(get_db)):
    # NOTE: first-login deliberately tells the user when there's no pending account
    # (these are admin-seeded, low enumeration value, and the UX needs the hint).
    # The sensitive forgot-password path below is uniform. Rate-limited per IP + phone.
    user, _ = await signup_service.find_pending_account_by_phone(db, body.phone)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account awaiting setup for this phone. Ask your admin to add you "
                   "first, or use 'Forgot password' if you've already set one.")
    res = await otp.request_otp(body.phone, otp.PURPOSE_SIGNUP)
    return OtpSentResponse(sent=res.sent, dev_code=res.dev_code)


@router.post("/signup/verify", response_model=TokenResponse,
             dependencies=[Depends(rate_limiter("signup_verify", 10, 300))])
async def signup_verify(body: SignupVerifyRequest, db: AsyncSession = Depends(get_db)):
    await otp.verify_otp(body.phone, otp.PURPOSE_SIGNUP, body.otp)
    user = await signup_service.complete_signup(
        db, phone=body.phone, password=body.password,
        first_name=body.first_name, last_name=body.last_name,
    )
    role = getattr(user, "role", None) or "staff"
    organisation_id = str(user.organisation_id) if getattr(user, "organisation_id", None) else None
    group_id = str(user.group_id) if getattr(user, "group_id", None) else None
    # auto-login
    return TokenResponse(
        access_token=create_access_token(user_id=str(user.id), role=role, organisation_id=organisation_id, group_id=group_id),
        refresh_token=create_refresh_token(user_id=str(user.id), role=role, organisation_id=organisation_id, group_id=group_id),
        user_id=str(user.id), role=role, organisation_id=organisation_id, group_id=group_id,
    )


# ----------------------------- forgot password (OTP) -----------------------------
@router.post("/password/request-otp", response_model=OtpSentResponse,
             dependencies=[Depends(rate_limiter("pw_otp", 5, 300))])
async def password_request_otp(body: ForgotOtpRequest, db: AsyncSession = Depends(get_db)):
    user, _ = await login_service.find_active_user_by_phone(db, body.phone)
    if user:
        res = await otp.request_otp(body.phone, otp.PURPOSE_RESET)
        return OtpSentResponse(sent=res.sent, dev_code=res.dev_code)
    # Unknown phone: respond with the SAME shape as a real request so the caller
    # can't enumerate which accounts exist (M9). In dev-OTP mode that means echoing
    # the fixed code too, so the response is byte-identical to a real one.
    return OtpSentResponse(
        sent=True,
        dev_code=(settings.otp_dev_code if settings.otp_dev_mode_active else None),
    )


@router.post("/password/reset",
             dependencies=[Depends(rate_limiter("pw_reset", 10, 300))])
async def password_reset(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    user, role = await login_service.find_active_user_by_phone(db, body.phone)
    if not user:
        # uniform error; OTP would also fail, but don't reveal existence
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code or phone.")
    await otp.verify_otp(body.phone, otp.PURPOSE_RESET, body.otp)
    user.password_hash = await hash_password_async(body.new_password)
    # A reset is the account-recovery action — kill any pre-existing (possibly
    # attacker-held) sessions so the reset actually regains control of the account.
    await invalidate_sessions(db, role, user.id)
    await db.commit()
    return {"detail": "Password updated. You can now log in."}


# ----------------------------- profile -----------------------------
@router.get("/user-profile/{user_id}")
async def get_user_profile(
    user_id: UUID,
    organisation_id: UUID = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not (
        principal.is_super_admin
        or str(principal.user_id) == str(user_id)
        or (principal.is_staff and organisation_id is not None and principal.can_access_organisation(organisation_id))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this profile")
    profile = await AuthService.get_user_profile(db, user_id, organisation_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found or not associated with this organisation")
    return profile
