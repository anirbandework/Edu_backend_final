"""Idempotent data seeds (sync). Safe to re-run.

- seed_super_admin: the platform super-admin, from .env (SUPER_ADMIN_*).
- seed_default_roles: one default RBAC role per (tenant, user_type) + assign roleless users.
- seed_dev_passwords: dev/local only — set a default password on users that have none.
"""
import uuid
from sqlalchemy import text

from app.core.config import settings
from app.auth_rbac.security.password import hash_password

_SEED_ROLES = [
    ("school_authority", "school_authorities", "Administrator", "administrator"),
    ("teacher", "teachers", "Teacher", "teacher"),
    ("student", "students", "Student", "student"),
]


def seed_super_admin(conn) -> str:
    if not settings.super_admin_password:
        return "  ! SUPER_ADMIN_PASSWORD not set — skipped super-admin seed"
    email = settings.super_admin_email.strip().lower()
    existing = conn.execute(text("SELECT id FROM super_admins WHERE email = :e"), {"e": email}).first()
    if existing:
        return f"  = super-admin already present ({email})"
    conn.execute(text(
        "INSERT INTO super_admins (id, email, phone, password_hash, first_name, last_name, status, is_deleted) "
        "VALUES (:id, :e, :p, :h, :f, :l, 'active', false)"
    ), {
        "id": str(uuid.uuid4()), "e": email,
        "p": (settings.super_admin_phone.strip() or None),
        "h": hash_password(settings.super_admin_password),
        "f": settings.super_admin_first_name, "l": settings.super_admin_last_name,
    })
    return f"  + seeded super-admin {email}"


def seed_default_roles(conn) -> str:
    tenant_ids = [str(r[0]) for r in conn.execute(text("SELECT id FROM tenants WHERE is_deleted = false")).fetchall()]
    roles = assigned = 0
    for tid in tenant_ids:
        for user_type, tbl, role_name, role_key in _SEED_ROLES:
            existing = conn.execute(text(
                "SELECT id FROM rbac_roles WHERE tenant_id=:t AND user_type=:u AND role_key=:k AND is_deleted=false"
            ), {"t": tid, "u": user_type, "k": role_key}).first()
            if existing:
                role_id = str(existing[0])
            else:
                role_id = str(uuid.uuid4())
                conn.execute(text(
                    "INSERT INTO rbac_roles (id, tenant_id, role_name, role_key, user_type, is_default, is_deleted) "
                    "VALUES (:id,:t,:n,:k,:u,true,false)"
                ), {"id": role_id, "t": tid, "n": role_name, "k": role_key, "u": user_type})
                roles += 1
            res = conn.execute(text(
                f"UPDATE {tbl} SET rbac_role_id=:rid WHERE tenant_id=:t AND rbac_role_id IS NULL"
            ), {"rid": role_id, "t": tid})
            assigned += res.rowcount or 0
    return f"  + default roles: created {roles}, assigned {assigned} users"


def seed_dev_passwords(conn, password: str = "Password123!") -> str:
    pw = hash_password(password)
    total = 0
    for _, tbl, _, _ in _SEED_ROLES:
        res = conn.execute(text(f"UPDATE {tbl} SET password_hash=:h WHERE password_hash IS NULL"), {"h": pw})
        total += res.rowcount or 0
    return f"  + dev passwords: set on {total} users (password '{password}')"
