"""Module + tab catalog — the code source-of-truth for RBAC (like indusinfotechs'
STAFF_MODULE_KEYS / ADMIN_MODULE_KEYS / MODULE_TABS).

A *module* is a feature/page; *tabs* are sub-sections within it. Each module
declares its `audience` (which user types it applies to). Effective permissions
come from intersecting the organisation ceiling with the user's role (see service.py).
"""
from __future__ import annotations

# canonical user types (match the identity tables / JWT role claim)
AUTHORITY = "authority"
TEACHER = "teacher"
STUDENT = "student"
# "staff" = the unified dynamic-role user type. A staff role may be granted ANY
# module across every section (it is not audience-restricted); its pages come
# from an explicit allow-list of RoleModulePermission rows.
STAFF = "staff"
# TEACHER/STUDENT remain only as audience-list constants (presentational grouping in the
# page picker); they are NO LONGER creatable user types. The teacher/student distinction
# now lives in role CAPABILITIES (see capabilities.py) — every member role is 'staff'.
USER_TYPES = (AUTHORITY, STAFF)
# user_types that an admin may create an rbac_role for: admin-side (authority) or the
# unified dynamic member type (staff). No teacher/student — that is a capability now.
ROLE_USER_TYPES = (AUTHORITY, STAFF)

# Functional sections — used by the page-picker UI to group modules so an admin
# can compose a custom role from pages across areas.
SEC_CORE = "Core"
SEC_ADMIN = "Administration"
SEC_ACADEMICS = "Academics"
SEC_COMMS = "Communication"

# Audience groups — the OTHER way the page-picker can group: "who is this page
# meant for". Purely presentational; granting is still unrestricted cross-group.
AUD_COMMON = "Common (everyone)"
AUD_ADMIN = "For Admins"
AUD_TEACHER = "For Teachers & Faculty"
AUD_STUDENT = "For Students"
AUD_PARENT = "For Parents"  # reserved — populated when parent pages are added

# Which audience bucket each page belongs to (by module_key). Edit freely; a key
# not listed defaults to Common.
_AUDIENCE_GROUP = {
    "students": AUD_ADMIN, "enrollment": AUD_ADMIN, "rbac_management": AUD_ADMIN, "staff": AUD_ADMIN,
    "classes": AUD_TEACHER, "attendance": AUD_TEACHER, "send_notification": AUD_TEACHER,
    "exams": AUD_TEACHER, "my_classes": AUD_TEACHER, "quizzes": AUD_TEACHER,
    "assignments": AUD_STUDENT, "grades": AUD_STUDENT,
    "dashboard": AUD_COMMON, "profile": AUD_COMMON, "notifications": AUD_COMMON,
    "timetable": AUD_COMMON, "chat": AUD_COMMON,
}


# Pages an admin may NOT distribute to a dynamic 'staff' role because they are
# admin-only management tools. (The old teacher/student-coupled exclusions are gone —
# quizzes/assignments/grades are now on member_id and gate with require_authority_or_module,
# so a dynamic 'staff' role like "Teacher" CAN be granted them.)
_ADMIN_ONLY = {"rbac_management", "org_settings"}                  # admin's own tools
# my_classes/chat stay non-grantable for now (their FE screens/paths need post-teardown cleanup).
_NOT_STAFF_GRANTABLE = {"my_classes", "chat"}


def _m(key, name, icon, path, audience, premium=False, tabs=None, section=SEC_CORE, required=False):
    return {
        "module_key": key,
        "module_name": name,
        "icon": icon,
        "path": path,
        "audience": list(audience),
        "section": section,
        "audience_group": _AUDIENCE_GROUP.get(key, AUD_COMMON),
        # required = always-on, cannot be toggled off in the RBAC pickers and is
        # always present in the sidebar (e.g. Profile).
        "required": required,
        # admin_only: never distributed to dynamic roles nor part of an org plan.
        "admin_only": key in _ADMIN_ONLY,
        # staff_grantable: may be assigned to a dynamic 'staff' role (its endpoints
        # accept a staff-with-module). False = works only for canonical roles.
        "staff_grantable": key not in _ADMIN_ONLY and key not in _NOT_STAFF_GRANTABLE,
        "premium": premium,
        "tabs": tabs or [],          # list of (tab_key, tab_label)
    }


# Ordered module catalog — ONLY pages that have a real, working screen. Keep keys
# stable (persisted in permission rows). Each `path` must be a registered route.
MODULES = [
    # --- shared / core ---
    # Profile is REQUIRED: always on, every user always has it. It is currently the ONLY
    # page distributable to a dynamic role — the feature modules (exams/attendance/classes/
    # timetable/enrolment/quizzes/chat/notifications/students) were removed and will be
    # rebuilt later per the §9 recipe. For now, every non-admin user gets ONLY Profile.
    _m("profile", "Profile", "person", "/profile", [AUTHORITY, TEACHER, STUDENT],
       section=SEC_CORE, required=True),

    # --- authority (admin) tools — the admin's own sidebar ---
    _m("rbac_management", "Roles & Access", "admin_panel_settings", "/admin/roles", [AUTHORITY],
       section=SEC_ADMIN),
    _m("staff", "Staff & Users", "badge", "/admin/staff", [AUTHORITY], section=SEC_ADMIN),

    # --- Phase-0 spine (the universal academic structure every org type shares) ---
    # See important_documents/MODULE_MASTER_PLAN.md §3. `classes` is the generic
    # Class/Batch/Course container (NOT institution groups); it renders per org_type.
    _m("academic_session", "Academic Sessions", "calendar_today", "/admin/sessions", [AUTHORITY],
       section=SEC_CORE),
    _m("classes", "Classes & Batches", "groups", "/admin/classes", [AUTHORITY],
       section=SEC_CORE),
    _m("subjects", "Subjects", "menu_book", "/admin/subjects", [AUTHORITY],
       section=SEC_ACADEMICS),
    # --- Phase 1: Attendance + Timetable — staff-grantable so instructor roles get them ---
    _m("attendance", "Attendance", "fact_check", "/admin/attendance", [AUTHORITY],
       section=SEC_ACADEMICS),
    _m("timetable", "Timetable", "calendar_view_week", "/admin/timetable", [AUTHORITY],
       section=SEC_ACADEMICS),
    _m("org_settings", "Settings", "settings", "/admin/settings", [AUTHORITY],
       section=SEC_ADMIN),
]

# Premium modules default OFF at the organisation level (super-admin must enable).
PREMIUM_MODULE_KEYS = {m["module_key"] for m in MODULES if m["premium"]}

# Lookups
_BY_KEY = {m["module_key"]: m for m in MODULES}


def get_module(module_key: str):
    return _BY_KEY.get(module_key)


def modules_for(user_type: str):
    """Modules visible to a user type (its audience). For the unified 'staff'
    type there is NO audience restriction — every module is grantable."""
    if user_type == STAFF:
        return list(MODULES)
    return [m for m in MODULES if user_type in m["audience"]]


def module_keys_for(user_type: str):
    return [m["module_key"] for m in modules_for(user_type)]


def tab_keys(module_key: str):
    m = _BY_KEY.get(module_key)
    return [t[0] for t in (m["tabs"] if m else [])]
