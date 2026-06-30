"""The single, ordered list of idempotent schema migrations (no Alembic).

ORM models are the source of truth — `Base.metadata.create_all` creates NEW
tables; this list handles column/index/FK changes to EXISTING tables that
create_all won't touch. Every statement is safe to run repeatedly.

When you change a model: add the matching ALTER/CREATE here, run
run_local_migration, then check_schema_diff (local vs prod), then
run_production_migration.
"""

# (label, sql) — labels show up in the per-statement run log.
MIGRATIONS = [
    # ── auth: hashed passwords on the identity tables ────────────────────────
    ("authorities.password_hash",
     "ALTER TABLE authorities ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"),

    # ── rbac: assigned role pointer on identity tables ───────────────────────
    ("authorities.rbac_role_id",
     "ALTER TABLE authorities ADD COLUMN IF NOT EXISTS rbac_role_id UUID"),

    # (Academic-feature migrations — classes/attendances/enrollments/notifications —
    # were removed with those modules. Re-add here if/when those features return.)
    #
    # NOTE: the organisation is institution-agnostic — its columns are name / code /
    # org_type / head_name (NOT school_*). The ORM model is the source of truth, so
    # create_all builds them directly; no column-rename migration is needed on a
    # fresh DB. (An older school_*-schema DB no longer exists, so the one-off rename
    # migrations were removed.)

    # ── rbac: indexes + FK (ON DELETE SET NULL) on the role pointer ──────────
    ("ix authorities.rbac_role_id",
     "CREATE INDEX IF NOT EXISTS ix_authorities_rbac_role ON authorities (rbac_role_id)"),
    ("fk authorities.rbac_role_id",
     "ALTER TABLE authorities ADD CONSTRAINT fk_authorities_rbac_role "
     "FOREIGN KEY (rbac_role_id) REFERENCES rbac_roles(id) ON DELETE SET NULL"),

    # ── super-admin → admin → organisations model ──────────────────────────────────
    # Which admin (authority) created/owns an organisation. Lets one admin own
    # many organisations and the super-admin Organisations screen group organisations per admin.
    ("organisations.owner_authority_id",
     "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS owner_authority_id UUID"),
    ("fk organisations.owner_authority_id",
     "ALTER TABLE organisations ADD CONSTRAINT fk_organisations_owner_authority "
     "FOREIGN KEY (owner_authority_id) REFERENCES authorities(id) ON DELETE SET NULL"),
    ("index organisations.owner_authority_id",
     "CREATE INDEX IF NOT EXISTS ix_organisations_owner_authority ON organisations (owner_authority_id)"),
    # An admin is created by the super-admin BEFORE they create any organisation, so
    # their organisation_id starts NULL (their active organisation is set on first creation).
    ("authorities.organisation_id nullable",
     "ALTER TABLE authorities ALTER COLUMN organisation_id DROP NOT NULL"),
    # Login is by phone+password; email is optional on admins.
    ("authorities.email nullable",
     "ALTER TABLE authorities ALTER COLUMN email DROP NOT NULL"),

    # ── institution group: super-admin → group → admins + organisations ───────
    # An organisation belongs to an institution group (all the group's admins see
    # it). The column is model-defined; its FK + index live here (matching the
    # owner_authority_id pattern). authorities.group_id has its FK inline in the ORM.
    ("fk organisations.group_id",
     "ALTER TABLE organisations ADD CONSTRAINT fk_organisations_group "
     "FOREIGN KEY (group_id) REFERENCES institution_groups(id) ON DELETE SET NULL"),
    ("index organisations.group_id",
     "CREATE INDEX IF NOT EXISTS ix_organisations_group ON organisations (group_id)"),
    # NOTE: the per-group module-access ceilings (group_module_permissions /
    # group_tab_permissions, with role_enabled + admin_enabled) are ORM-defined, so
    # create_all builds them — no migration needed. They replace the old
    # organisation_module_permissions audience model.

    # ── scale: indexes on hot columns (100k+ users) ──────────────────────────
    # Login resolves a user by PHONE across authorities + members on every attempt;
    # list/permission queries filter by group_id / organisation_id / is_deleted.
    # Without these, those are sequential scans at scale.
    ("ix authorities.phone",
     "CREATE INDEX IF NOT EXISTS ix_authorities_phone ON authorities (phone)"),
    ("ix members.phone",
     "CREATE INDEX IF NOT EXISTS ix_members_phone ON members (phone)"),
    ("ix authorities.group_id",
     "CREATE INDEX IF NOT EXISTS ix_authorities_group ON authorities (group_id)"),
    ("ix authorities.organisation_id",
     "CREATE INDEX IF NOT EXISTS ix_authorities_org ON authorities (organisation_id)"),
    ("ix members.organisation_id+is_deleted",
     "CREATE INDEX IF NOT EXISTS ix_members_org_active ON members (organisation_id, is_deleted)"),
    ("ix members.rbac_role_id",
     "CREATE INDEX IF NOT EXISTS ix_members_rbac_role ON members (rbac_role_id)"),
    ("ix organisations.group_id+is_deleted",
     "CREATE INDEX IF NOT EXISTS ix_organisations_group_active ON organisations (group_id, is_deleted)"),

    # ── session revocation: per-user "invalidate all tokens before this time" ──
    # Stamped to now() on password change/reset so every prior access+refresh token
    # is rejected (token.iat < this). Checked per request (Redis-cached, DB fallback).
    ("authorities.sessions_invalidated_at",
     "ALTER TABLE authorities ADD COLUMN IF NOT EXISTS sessions_invalidated_at TIMESTAMPTZ"),
    ("members.sessions_invalidated_at",
     "ALTER TABLE members ADD COLUMN IF NOT EXISTS sessions_invalidated_at TIMESTAMPTZ"),
    ("super_admins.sessions_invalidated_at",
     "ALTER TABLE super_admins ADD COLUMN IF NOT EXISTS sessions_invalidated_at TIMESTAMPTZ"),

    # ── integrity: DB-level phone uniqueness (phone is the login id) ──────────
    # Enforced per identity table on NON-deleted rows (a soft-deleted user frees
    # their phone). Closes the app-code-only TOCTOU race (H14) that let concurrent
    # inserts create duplicate phones → cross-tenant login shadowing. If either of
    # these is reported "skipped" due to existing duplicates, dedup first then re-run.
    ("uq members.phone (active)",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_members_phone_active "
     "ON members (phone) WHERE is_deleted = false"),
    ("uq authorities.phone (active)",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_authorities_phone_active "
     "ON authorities (phone) WHERE is_deleted = false"),

    # ── cleanup: the invitation / signup-link system was removed (onboarding is now
    #    password-less first-login via phone + OTP). Drop the orphaned, never-used table.
    ("drop invitations table",
     "DROP TABLE IF EXISTS invitations CASCADE"),

    # ── members.phone nullable: a member can be created name-only (the org's
    #    auto-created head/Principal), gaining a phone later to enable login.
    ("members.phone nullable",
     "ALTER TABLE members ALTER COLUMN phone DROP NOT NULL"),

    # ── per-role custom fields: admin-defined extra fields collected when adding a
    #    user to a role (grade, parent name, address, ...). JSON list of field defs.
    #    Filled values are stored on members.profile['custom_fields'] (existing JSON).
    ("rbac_roles.custom_fields",
     "ALTER TABLE rbac_roles ADD COLUMN IF NOT EXISTS custom_fields JSONB NOT NULL DEFAULT '[]'::jsonb"),

    # ── scale: indexes for the Staff & Users search/filter at 100k+ members/org ──
    # The directory search uses ILIKE '%term%' (leading wildcard) on name/email/phone,
    # which a btree index can't serve. pg_trgm GIN indexes make it index-backed.
    ("extension pg_trgm",
     "CREATE EXTENSION IF NOT EXISTS pg_trgm"),
    ("ix members.first_name trgm",
     "CREATE INDEX IF NOT EXISTS ix_members_first_trgm ON members USING gin (first_name gin_trgm_ops)"),
    ("ix members.last_name trgm",
     "CREATE INDEX IF NOT EXISTS ix_members_last_trgm ON members USING gin (last_name gin_trgm_ops)"),
    # The directory search also ILIKEs email + phone (leading wildcard) — index those too.
    ("ix members.email trgm",
     "CREATE INDEX IF NOT EXISTS ix_members_email_trgm ON members USING gin (email gin_trgm_ops)"),
    ("ix members.phone trgm",
     "CREATE INDEX IF NOT EXISTS ix_members_phone_trgm ON members USING gin (phone gin_trgm_ops)"),
    # staff_id is a human code — keep it unique per org on live rows (defends bulk imports).
    # (Skipped automatically if legacy duplicates exist; dedup then re-run.)
    ("uq members.staff_id (active)",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_members_staff_id_active "
     "ON members (organisation_id, staff_id) WHERE is_deleted = false"),
    # rbac_roles.organisation_id: model declares index=True but create_all won't add it
    # to an already-existing table — ensure it for the per-org role list/lookup.
    ("ix rbac_roles.organisation_id",
     "CREATE INDEX IF NOT EXISTS ix_rbac_roles_org ON rbac_roles (organisation_id)"),
    # Role-filtered staff list + count_role_users both filter rbac_role_id on live rows.
    ("ix members.rbac_role_id (active)",
     "CREATE INDEX IF NOT EXISTS ix_members_rbac_role_active "
     "ON members (rbac_role_id) WHERE is_deleted = false"),
]
