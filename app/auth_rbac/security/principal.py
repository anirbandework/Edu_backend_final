"""The authenticated caller, resolved from a verified access token."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import uuid

ROLE_SUPER_ADMIN = "super_admin"
ROLE_AUTHORITY = "school_authority"
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
# Unified dynamic-role staff (faculty / principal / HOD / office / ...). Their
# real permissions come from the rbac_role assigned to them, NOT a coarse bucket.
ROLE_STAFF = "staff"

# Roles considered "staff" (may manage tenant-scoped resources via the coarse
# is_staff/require_staff checks). NOTE: ROLE_STAFF is deliberately EXCLUDED — a
# dynamic-role user's access is page-driven (require_module_access / their
# rbac_role's grants), never the blanket is_staff property. Including it here
# would let a zero-permission staff user pass every inline `principal.is_staff`
# authorization check (notifications, quizzes, timetable, analytics, ...).
STAFF_ROLES = {ROLE_SUPER_ADMIN, ROLE_AUTHORITY, ROLE_TEACHER}


@dataclass(frozen=True)
class Principal:
    """Server-derived identity. NEVER constructed from client-supplied fields
    other than a verified token."""
    user_id: str
    role: str
    tenant_id: Optional[str]
    jti: Optional[str] = None

    @property
    def is_super_admin(self) -> bool:
        return self.role == ROLE_SUPER_ADMIN

    @property
    def is_authority(self) -> bool:
        return self.role == ROLE_AUTHORITY

    @property
    def is_dynamic_staff(self) -> bool:
        """A user in the unified staff_users table (role/pages defined entirely
        by their assigned rbac_role)."""
        return self.role == ROLE_STAFF

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def tenant_uuid(self) -> Optional[uuid.UUID]:
        if not self.tenant_id:
            return None
        try:
            return uuid.UUID(str(self.tenant_id))
        except (ValueError, TypeError):
            return None

    @property
    def user_uuid(self) -> Optional[uuid.UUID]:
        try:
            return uuid.UUID(str(self.user_id))
        except (ValueError, TypeError):
            return None

    def can_access_tenant(self, tenant_id) -> bool:
        """Super admins can act across tenants; everyone else is locked to their own."""
        if self.is_super_admin:
            return True
        if tenant_id is None:
            return False
        return str(tenant_id) == str(self.tenant_id)
