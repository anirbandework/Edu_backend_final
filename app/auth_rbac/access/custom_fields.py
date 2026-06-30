"""Per-role custom fields.

A dynamic role may define extra fields (grade, parent name, address, ...) that are
collected when a user is added to that role. Two halves:

  • DEFINITIONS live on ``rbac_roles.custom_fields`` (JSONB list of
    ``{key, label, type, required, options?}``).
  • VALUES live on ``members.profile['custom_fields']`` (``{key: value}``).

This module owns both: ``normalize_definitions`` cleans the admin's field list on
role save (assigning a stable ``key``), and ``validate_values`` checks a submitted
user's values against the role's definitions on staff create/update.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime

# Supported input types (kept in sync with the Flutter role editor + user form).
FIELD_TYPES = {"text", "textarea", "number", "email", "phone", "date", "select", "bool"}

_MAX_FIELDS = 40
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_KEY_RE = re.compile(r"[^a-z0-9]+")
# Labels reserved by the built-in identity columns — a custom field may not reuse them,
# or it would shadow the built-in column in the bulk-import template (imports.py).
_RESERVED_LABELS = {"first name", "last name", "name", "phone", "email", "designation", "position"}


def _gen_key(label: str) -> str:
    """A stable, readable key from a label plus a short random suffix (so renaming
    the label later never collides with or breaks an existing field's stored values)."""
    base = _KEY_RE.sub("_", (label or "").strip().lower()).strip("_")[:32] or "field"
    return f"{base}_{secrets.token_hex(2)}"


def normalize_definitions(raw) -> list[dict]:
    """Validate + clean a role's custom-field DEFINITIONS for storage.

    Preserves an existing ``key`` (so stored values stay attached across label edits),
    assigns one to new fields, dedups keys, and caps the count. Raises ``ValueError``
    with a user-facing message on anything malformed. ``None`` -> ``[]``.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Custom fields must be a list.")
    if len(raw) > _MAX_FIELDS:
        raise ValueError(f"A role can have at most {_MAX_FIELDS} custom fields.")
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each custom field must be an object.")
        label = str(item.get("label") or "").strip()
        if not label:
            raise ValueError("Every custom field needs a label.")
        if label.lower() in _RESERVED_LABELS:
            raise ValueError(f"'{label}' is a built-in field — choose a different label.")
        ftype = str(item.get("type") or "text").strip().lower()
        if ftype not in FIELD_TYPES:
            raise ValueError(f"Unknown field type '{ftype}'.")
        key = str(item.get("key") or "").strip()
        if not key or key in seen:
            key = _gen_key(label)
            while key in seen:
                key = _gen_key(label)
        seen.add(key)
        field = {
            "key": key,
            "label": label[:80],
            "type": ftype,
            "required": bool(item.get("required")),
        }
        if ftype == "select":
            opts = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
            if not opts:
                raise ValueError(f"Dropdown '{label}' needs at least one option.")
            field["options"] = opts[:50]
        out.append(field)
    return out


def validate_values(definitions, values) -> dict:
    """Validate a submitted user's VALUES against a role's definitions.

    Returns a cleaned ``{key: value}`` dict containing only known keys. Raises
    ``ValueError`` (user-facing) when a required field is blank or a value is
    malformed for its type. Unknown / extra keys are dropped.
    """
    defs = definitions or []
    values = values or {}
    if not isinstance(values, dict):
        raise ValueError("Custom field values must be an object.")
    cleaned: dict = {}
    for f in defs:
        key = f.get("key")
        label = f.get("label", key)
        ftype = f.get("type", "text")
        raw = values.get(key)
        is_blank = raw is None or (isinstance(raw, str) and not raw.strip())
        if is_blank:
            if f.get("required"):
                raise ValueError(f"'{label}' is required.")
            continue
        if ftype == "bool":
            cleaned[key] = raw if isinstance(raw, bool) else \
                str(raw).strip().lower() in ("1", "true", "yes", "on")
            continue
        val = str(raw).strip()
        if ftype == "number":
            try:
                num = float(val)
            except ValueError:
                raise ValueError(f"'{label}' must be a number.")
            import math
            if not math.isfinite(num):  # reject NaN / Infinity
                raise ValueError(f"'{label}' must be a real number.")
        elif ftype == "email":
            if not _EMAIL_RE.match(val):
                raise ValueError(f"'{label}' must be a valid email address.")
        elif ftype == "phone":
            if len(re.sub(r"\D", "", val)) < 7:
                raise ValueError(f"'{label}' must be a valid phone number.")
        elif ftype == "date":
            try:
                datetime.fromisoformat(val)
            except ValueError:
                raise ValueError(f"'{label}' must be a valid date (YYYY-MM-DD).")
        elif ftype == "select":
            if val not in (f.get("options") or []):
                raise ValueError(f"'{label}' must be one of its allowed options.")
        cleaned[key] = val[:1000]
    return cleaned
