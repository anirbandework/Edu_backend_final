"""Authentication endpoints.

Public:   login (phone+password), refresh, signup (invite+OTP), forgot-password (OTP), GET invite.
Authed:   logout, me, user-profile, create invites (super-admin -> authority; authority -> teacher/student).
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
from ..services.auth_service import AuthService
from ..services import login_service, invitation_service, signup_service
from ...school_authority_management.models.school_authority import SchoolAuthority
from ...tenant_management.services.tenant_service import TenantService
from ...tenant_management.schemas.tenant_schemas import TenantCreate
from ..security import otp
from ..security.tokens import (
    create_access_token, create_refresh_token, decode_token, TokenError, REFRESH,
)
from ..security.password import hash_password, verify_password
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
    tenant_id: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class InviteAuthorityRequest(BaseModel):
    tenant_id: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None


class InviteStaffRequest(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    grade_level: Optional[int] = None  # student only
    section: Optional[str] = None      # student only


class InviteResponse(BaseModel):
    token: str
    invite_url: str
    role: str
    expires_at: str
    target_user_id: Optional[str] = None


class InvitePublicInfo(BaseModel):
    role: str
    tenant_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class SignupOtpRequest(BaseModel):
    token: str
    phone: str


class OtpSentResponse(BaseModel):
    sent: bool
    dev_code: Optional[str] = None  # only populated in dev mode


class SignupVerifyRequest(BaseModel):
    token: str
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
@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    identity = await login_service.authenticate(db, identifier=body.phone, password=body.password)
    if not identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or password")
    return TokenResponse(
        access_token=create_access_token(user_id=identity.user_id, role=identity.role, tenant_id=identity.tenant_id),
        refresh_token=create_refresh_token(user_id=identity.user_id, role=identity.role, tenant_id=identity.tenant_id),
        user_id=identity.user_id, role=identity.role, tenant_id=identity.tenant_id,
    )


@router.get("/schools")
async def list_schools(db: AsyncSession = Depends(get_db)):
    """Public: minimal active-school list for the login picker (no sensitive fields)."""
    from sqlalchemy import select
    from ...tenant_management.models.tenant import Tenant
    rows = (await db.execute(
        select(Tenant)
        .where(Tenant.is_active == True, Tenant.is_deleted == False)  # noqa: E712
        .order_by(Tenant.school_name)
    )).scalars().all()
    return [
        {
            "id": str(t.id),
            "school_name": t.school_name,
            "school_code": getattr(t, "school_code", None),
            "address": getattr(t, "address", None),
            "school_type": getattr(t, "school_type", None),
            "total_students": getattr(t, "total_students", 0) or 0,
            "total_teachers": getattr(t, "total_teachers", 0) or 0,
            "is_active": True,
        }
        for t in rows
    ]


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token, expected_type=REFRESH)
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    return TokenResponse(
        access_token=create_access_token(user_id=payload["sub"], role=payload.get("role", ""), tenant_id=payload.get("tenant_id")),
        refresh_token=body.refresh_token,
        user_id=payload["sub"], role=payload.get("role", ""), tenant_id=payload.get("tenant_id"),
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
    return {"user_id": principal.user_id, "role": principal.role, "tenant_id": principal.tenant_id}


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
    if not getattr(user, "password_hash", None) or not verify_password(
        body.current_password, user.password_hash
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"detail": "Password changed successfully"}


# ----------------------------- invitations -----------------------------
@router.post("/invites/authority", response_model=InviteResponse)
async def invite_authority(
    body: InviteAuthorityRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Super-admin invites a School Authority into a given school."""
    user = await signup_service.create_invited_user(
        db, role="school_authority", tenant_id=body.tenant_id,
        first_name=body.first_name, last_name=body.last_name,
        email=body.email, phone=body.phone,
    )
    inv = await invitation_service.create_invitation(
        db, principal, role="school_authority", tenant_id=body.tenant_id,
        phone=body.phone, email=body.email, first_name=body.first_name,
        last_name=body.last_name, target_user_id=str(user.id),
    )
    return InviteResponse(token=inv.token, invite_url=invitation_service.signup_url(inv.token),
                          role=inv.role, expires_at=_iso(inv.expires_at), target_user_id=str(user.id))


@router.post("/invites/teacher", response_model=InviteResponse)
async def invite_teacher(
    body: InviteStaffRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """School authority invites a Teacher into their school."""
    user = await signup_service.create_invited_user(
        db, role="teacher", tenant_id=principal.tenant_id,
        first_name=body.first_name, last_name=body.last_name,
        email=body.email, phone=body.phone,
    )
    inv = await invitation_service.create_invitation(
        db, principal, role="teacher", phone=body.phone, email=body.email,
        first_name=body.first_name, last_name=body.last_name, target_user_id=str(user.id),
    )
    return InviteResponse(token=inv.token, invite_url=invitation_service.signup_url(inv.token),
                          role=inv.role, expires_at=_iso(inv.expires_at), target_user_id=str(user.id))


@router.post("/invites/student", response_model=InviteResponse)
async def invite_student(
    body: InviteStaffRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """School authority invites a Student into their school."""
    extra = {}
    if body.grade_level is not None:
        extra["grade_level"] = body.grade_level
    if body.section is not None:
        extra["section"] = body.section
    user = await signup_service.create_invited_user(
        db, role="student", tenant_id=principal.tenant_id,
        first_name=body.first_name, last_name=body.last_name,
        email=body.email, phone=body.phone, extra=extra,
    )
    inv = await invitation_service.create_invitation(
        db, principal, role="student", phone=body.phone, email=body.email,
        first_name=body.first_name, last_name=body.last_name, target_user_id=str(user.id),
    )
    return InviteResponse(token=inv.token, invite_url=invitation_service.signup_url(inv.token),
                          role=inv.role, expires_at=_iso(inv.expires_at), target_user_id=str(user.id))


# ----------------------------- super-admin: ADMINS -----------------------------
# Login is by phone + password, so both are compulsory; email is optional.
class CreateAdminRequest(BaseModel):
    first_name: str
    last_name: str
    phone: str
    password: str
    email: Optional[str] = None
    modules: list[str] = Field(default_factory=list)  # granted module keys


class UpdateAdminRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class UpdateAdminModulesRequest(BaseModel):
    modules: list[str]


class AdminStatusRequest(BaseModel):
    is_active: bool


class ResetPasswordRequest(BaseModel):
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


def _admin_dict(sa: SchoolAuthority, school_count: int = 0) -> dict:
    return {
        "id": str(sa.id),
        "first_name": sa.first_name,
        "last_name": sa.last_name,
        "email": sa.email,
        "phone": sa.phone,
        "status": sa.status,
        "modules": _admin_modules(sa.permissions),
        "school_count": school_count,
    }


@router.post("/admins")
async def create_admin(
    body: CreateAdminRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Super-admin creates an ADMIN (school_authority) with NO school yet, the
    pages they may use, and a phone+password they log in with immediately. Email
    is optional; the admin creates their school(s) after first login."""
    if not body.phone.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone is required.")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    await invitation_service.assert_phone_available(db, body.phone)

    # Reuse the standard creation (sets authority_id, position, etc.), then
    # activate immediately with the chosen password.
    user = await signup_service.create_invited_user(
        db, role="school_authority", tenant_id=None,
        first_name=body.first_name, last_name=body.last_name,
        email=(body.email.strip() or None) if body.email else None, phone=body.phone.strip(),
        extra={"permissions": {"modules": body.modules}},
    )
    user.password_hash = hash_password(body.password)
    user.status = "active"
    await db.commit()
    await db.refresh(user)
    return {**_admin_dict(user), "message": "Admin created"}


@router.get("/admins")
async def list_admins(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """All admins with their owned-school count + granted modules + status."""
    rows = (await db.execute(text(
        """
        SELECT a.id, a.first_name, a.last_name, a.email, a.phone, a.status, a.permissions,
               (SELECT COUNT(*) FROM tenants t
                 WHERE t.owner_authority_id = a.id AND t.is_deleted = false) AS school_count
        FROM school_authorities a
        WHERE a.is_deleted = false AND a.role = 'school_authority'
        ORDER BY a.created_at DESC
        """
    ))).mappings().all()
    return [{
        "id": str(r["id"]),
        "first_name": r["first_name"],
        "last_name": r["last_name"],
        "email": r["email"],
        "phone": r["phone"],
        "status": r["status"],
        "modules": _admin_modules(r["permissions"]),
        "school_count": int(r["school_count"] or 0),
    } for r in rows]


@router.put("/admins/{admin_id}/modules")
async def update_admin_modules(
    admin_id: UUID,
    body: UpdateAdminModulesRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Set which modules/pages an admin (and all their schools) may use."""
    sa = (await db.execute(select(SchoolAuthority).where(SchoolAuthority.id == admin_id))).scalar_one_or_none()
    if not sa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
    perms = dict(sa.permissions) if isinstance(sa.permissions, dict) else {}
    perms["modules"] = body.modules
    sa.permissions = perms
    await db.commit()
    return {"id": str(admin_id), "modules": body.modules, "message": "Modules updated"}


async def _load_admin(db: AsyncSession, admin_id: UUID) -> SchoolAuthority:
    sa = (await db.execute(
        select(SchoolAuthority).where(
            SchoolAuthority.id == admin_id, SchoolAuthority.is_deleted == False
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
        await invitation_service.assert_phone_available(db, body.phone, exclude_user_id=str(sa.id))
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
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Set a new password for an admin (login is phone+password)."""
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    sa = await _load_admin(db, admin_id)
    sa.password_hash = hash_password(body.password)
    await db.commit()
    return {"id": str(admin_id), "message": "Password reset"}


@router.delete("/admins/{admin_id}")
async def delete_admin(
    admin_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Soft-delete an admin and deactivate the schools they own."""
    sa = await _load_admin(db, admin_id)
    sa.is_deleted = True
    sa.status = "inactive"
    # Deactivate (don't hard-delete) the admin's schools so data is preserved.
    res = await db.execute(text(
        "UPDATE tenants SET is_active = false WHERE owner_authority_id = :oid AND is_deleted = false"
    ), {"oid": str(admin_id)})
    await db.commit()
    return {"id": str(admin_id), "schools_deactivated": res.rowcount or 0,
            "message": "Admin deleted"}


# ----------------------------- admin: SCHOOL SWITCHER -----------------------------
@router.get("/my-schools")
async def my_schools(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """Schools owned by the current admin (feeds the active-school switcher)."""
    rows = (await db.execute(text(
        """
        SELECT id, school_name, school_code, is_active
        FROM tenants
        WHERE owner_authority_id = :oid AND is_deleted = false
        ORDER BY created_at DESC
        """
    ), {"oid": str(principal.user_id)})).mappings().all()
    return [{"id": str(r["id"]), "school_name": r["school_name"],
             "school_code": r["school_code"], "is_active": r["is_active"]} for r in rows]


@router.post("/switch-school/{tenant_id}", response_model=TokenResponse)
async def switch_school(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """Re-scope the admin's session to one of THEIR schools (returns a new JWT)."""
    owns = (await db.execute(text(
        "SELECT 1 FROM tenants WHERE id = :tid AND owner_authority_id = :oid "
        "AND is_deleted = false LIMIT 1"
    ), {"tid": str(tenant_id), "oid": str(principal.user_id)})).first()
    if not owns:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not own this school")
    # Remember it as the admin's active school.
    await db.execute(text(
        "UPDATE school_authorities SET tenant_id = :tid WHERE id = :oid"
    ), {"tid": str(tenant_id), "oid": str(principal.user_id)})
    await db.commit()
    tid = str(tenant_id)
    return TokenResponse(
        access_token=create_access_token(user_id=str(principal.user_id), role=principal.role, tenant_id=tid),
        refresh_token=create_refresh_token(user_id=str(principal.user_id), role=principal.role, tenant_id=tid),
        user_id=str(principal.user_id), role=principal.role, tenant_id=tid,
    )


@router.post("/schools")
async def create_my_school(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority),
):
    """An ADMIN creates a school they own. (The /api/v1/tenants router is
    super-admin-only; this is the admin's self-service create.) The new school is
    stamped with owner_authority_id = the admin and becomes their active school
    if they had none."""
    service = TenantService(db)
    tenant_dict = body.model_dump()
    if not tenant_dict.get("school_code"):
        tenant_dict["school_code"] = await service.generate_school_code(tenant_dict["school_name"])
    try:
        tenant = await service.create(tenant_dict)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A school with these details already exists.")
    if not tenant:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="School creation failed")
    await db.execute(text(
        "UPDATE tenants SET owner_authority_id = :oid WHERE id = :tid"
    ), {"oid": str(principal.user_id), "tid": str(tenant.id)})
    await db.execute(text(
        "UPDATE school_authorities SET tenant_id = :tid WHERE id = :oid AND tenant_id IS NULL"
    ), {"tid": str(tenant.id), "oid": str(principal.user_id)})
    await db.commit()
    return {"id": str(tenant.id), "school_name": tenant.school_name,
            "school_code": tenant.school_code, "message": "School created"}


@router.get("/invites/{token}", response_model=InvitePublicInfo)
async def get_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Public: the signup screen calls this to render the invite (role, prefilled name/phone)."""
    inv = await invitation_service.get_valid_invitation(db, token)
    return InvitePublicInfo(role=inv.role, tenant_id=str(inv.tenant_id) if inv.tenant_id else None,
                            first_name=inv.first_name, last_name=inv.last_name,
                            phone=inv.phone, email=inv.email)


# ----------------------------- signup (invite + OTP) -----------------------------
@router.post("/signup/request-otp", response_model=OtpSentResponse)
async def signup_request_otp(body: SignupOtpRequest, db: AsyncSession = Depends(get_db)):
    inv = await invitation_service.get_valid_invitation(db, body.token)
    # if the invite fixed a phone, the signup phone must match it
    if inv.phone and inv.phone.strip() and inv.phone.strip() != body.phone.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone does not match the invitation.")
    # reject phones already registered to an active account
    await invitation_service.assert_phone_available(db, body.phone, exclude_user_id=str(inv.target_user_id) if inv.target_user_id else None)
    res = await otp.request_otp(body.phone, otp.PURPOSE_SIGNUP)
    return OtpSentResponse(sent=res.sent, dev_code=res.dev_code)


@router.post("/signup/verify", response_model=TokenResponse)
async def signup_verify(body: SignupVerifyRequest, db: AsyncSession = Depends(get_db)):
    inv = await invitation_service.get_valid_invitation(db, body.token)
    if inv.phone and inv.phone.strip() and inv.phone.strip() != body.phone.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone does not match the invitation.")
    await otp.verify_otp(body.phone, otp.PURPOSE_SIGNUP, body.otp)
    user = await signup_service.complete_signup(
        db, inv, phone=body.phone, password=body.password,
        first_name=body.first_name, last_name=body.last_name,
    )
    role = getattr(user, "role", inv.role) or inv.role
    tenant_id = str(user.tenant_id) if getattr(user, "tenant_id", None) else None
    # auto-login
    return TokenResponse(
        access_token=create_access_token(user_id=str(user.id), role=role, tenant_id=tenant_id),
        refresh_token=create_refresh_token(user_id=str(user.id), role=role, tenant_id=tenant_id),
        user_id=str(user.id), role=role, tenant_id=tenant_id,
    )


# ----------------------------- forgot password (OTP) -----------------------------
@router.post("/password/request-otp", response_model=OtpSentResponse)
async def password_request_otp(body: ForgotOtpRequest, db: AsyncSession = Depends(get_db)):
    user, _ = await login_service.find_active_user_by_phone(db, body.phone)
    # Always respond the same way to avoid leaking which phones exist...
    if not user:
        return OtpSentResponse(sent=True, dev_code=None)
    res = await otp.request_otp(body.phone, otp.PURPOSE_RESET)
    return OtpSentResponse(sent=res.sent, dev_code=res.dev_code)


@router.post("/password/reset")
async def password_reset(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    user, _ = await login_service.find_active_user_by_phone(db, body.phone)
    if not user:
        # uniform error; OTP would also fail, but don't reveal existence
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code or phone.")
    await otp.verify_otp(body.phone, otp.PURPOSE_RESET, body.otp)
    from ..security.password import hash_password
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"detail": "Password updated. You can now log in."}


# ----------------------------- profile -----------------------------
@router.get("/user-profile/{user_id}")
async def get_user_profile(
    user_id: UUID,
    tenant_id: UUID = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not (
        principal.is_super_admin
        or str(principal.user_id) == str(user_id)
        or (principal.is_staff and tenant_id is not None and principal.can_access_tenant(tenant_id))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this profile")
    profile = await AuthService.get_user_profile(db, user_id, tenant_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found or not associated with this tenant")
    return profile
