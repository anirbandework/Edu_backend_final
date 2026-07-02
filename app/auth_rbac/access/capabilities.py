"""Role capabilities — the behaviour flags that make EduAssist org-type-agnostic.

A dynamic role (rbac_roles) carries TWO orthogonal things:
  • page permissions  (role_module_permissions) — which SCREENS it opens.
  • CAPABILITIES       (rbac_roles.capabilities)  — what FUNCTION its members serve
                                                    in academic flows.

Capability KEYS are a small, fixed, system-level vocabulary of BEHAVIOURS (not
person-types): every org type shares the same behaviours; only the role NAMES
mapped to them are admin-defined, and the user-facing WORDS come from
org_settings.terminology. So every module asks "which roles can teach?"
(``roles_with_capability(org, 'instructor')``) — never "who is a teacher".

See important_documents/CONNECTIONS_AND_FLOW.md §1–§2 for the full design.
"""
from __future__ import annotations

# Ordered catalog of the fixed capability vocabulary. `label`/`description` are the
# generic defaults shown in the Roles editor; the live UI relabels them through
# org_settings.terminology (e.g. "learner" → "Student"/"Trainee").
CAPABILITIES = [
    {"key": "learner",     "label": "Is taught (learner)",
     "description": "Members are taught: attendance is taken for them; they receive marks, report cards and fees."},
    {"key": "instructor",  "label": "Teaches (instructor)",
     "description": "Members teach/lead a class: they mark attendance and enter marks."},
    {"key": "class_head",  "label": "Can lead a class (class head)",
     "description": "Members can be assigned as a class's head/coordinator/mentor (one per class)."},
    {"key": "guardian",    "label": "Is a guardian",
     "description": "Members are parents/guardians and can be linked to a learner."},
    {"key": "admin_staff", "label": "Operational staff",
     "description": "Non-teaching operational staff (office, accounts, front-desk). Not a learner or instructor."},
]

# Fast membership set for validation.
CAPABILITY_KEYS = frozenset(c["key"] for c in CAPABILITIES)

# The capabilities that define how a member PARTICIPATES inside a class. A class
# membership's `capacity` (see class_management) is resolved from these — its options
# are exactly the participant capabilities of THAT member's role, never a hardcoded
# student/teacher/assistant list.
PARTICIPANT_CAPABILITIES = ("instructor", "class_head", "learner")


def normalize_capabilities(raw) -> list[str]:
    """Validate + clean a role's capability list for storage.

    Keeps order, drops duplicates, and rejects unknown keys with a user-facing
    ``ValueError``. ``None`` -> ``[]``.
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError("Capabilities must be a list.")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = str(item or "").strip().lower()
        if not key:
            continue
        if key not in CAPABILITY_KEYS:
            raise ValueError(f"Unknown capability '{key}'.")
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def has_capability(capabilities, key: str) -> bool:
    """True iff the (stored) capability list grants ``key``."""
    return key in (capabilities or [])


def participant_capabilities(capabilities) -> list[str]:
    """The subset of a role's capabilities that define a class-participation capacity,
    in canonical order (instructor → class_head → learner)."""
    caps = capabilities or []
    return [c for c in PARTICIPANT_CAPABILITIES if c in caps]
