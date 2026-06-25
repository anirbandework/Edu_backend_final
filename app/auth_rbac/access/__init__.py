"""Module/tab RBAC (indusinfotechs-style), adapted for EduAssist's tenants.

3 tiers:
  Tier 0 (super_admin): which modules/tabs a TENANT may use     -> tenant_module/tab_permission
  Tier 1 (school_authority): custom ROLES + their module/tab perms -> roles + role_module/tab_permission
  Tier 2 (authority/teacher/student): assigned ONE role (user_roles) -> inherits its perms

Effective access = tenant_enabled AND role_enabled  (missing rows default to enabled).
"""
