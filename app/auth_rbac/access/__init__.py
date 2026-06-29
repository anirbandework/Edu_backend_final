"""Module/tab RBAC (indusinfotechs-style), adapted for EduAssist's organisations.

3 tiers:
  Tier 0 (super_admin): which modules/tabs a ORGANISATION may use     -> organisation_module/tab_permission
  Tier 1 (authority): custom ROLES + their module/tab perms -> roles + role_module/tab_permission
  Tier 2 (authority/teacher/student): assigned ONE role (user_roles) -> inherits its perms

Effective access = organisation_enabled AND role_enabled  (missing rows default to enabled).
"""
