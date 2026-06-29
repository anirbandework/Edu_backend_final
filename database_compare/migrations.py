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
    ("school_authorities.password_hash",
     "ALTER TABLE school_authorities ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"),

    # ── rbac: assigned role pointer on identity tables ───────────────────────
    ("school_authorities.rbac_role_id",
     "ALTER TABLE school_authorities ADD COLUMN IF NOT EXISTS rbac_role_id UUID"),

    # ── scalability: composite indexes on hot query paths ────────────────────
    ("ix classes(tenant,year)",
     "CREATE INDEX IF NOT EXISTS ix_classes_tenant_year ON classes (tenant_id, academic_year)"),
    ("ix attendances(tenant,user,date)",
     "CREATE INDEX IF NOT EXISTS ix_attendances_tenant_user_date ON attendances (tenant_id, user_id, attendance_date)"),
    ("ix attendances(tenant,date)",
     "CREATE INDEX IF NOT EXISTS ix_attendances_tenant_date ON attendances (tenant_id, attendance_date)"),
    ("ix enrollments(class,year)",
     "CREATE INDEX IF NOT EXISTS ix_enrollments_class_year ON enrollments (class_id, academic_year)"),

    # ── enrollments: denormalized tenant_id for direct tenant scoping ────────
    ("enrollments.tenant_id col",
     "ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS tenant_id UUID"),
    ("enrollments.tenant_id backfill",
     "UPDATE enrollments e SET tenant_id = c.tenant_id FROM classes c "
     "WHERE e.class_id = c.id AND e.tenant_id IS NULL"),
    ("ix enrollments.tenant_id",
     "CREATE INDEX IF NOT EXISTS ix_enrollments_tenant_id ON enrollments (tenant_id)"),
    ("fk enrollments.tenant_id",
     "ALTER TABLE enrollments ADD CONSTRAINT fk_enrollments_tenant "
     "FOREIGN KEY (tenant_id) REFERENCES tenants(id)"),
    ("enrollments.tenant_id not null",
     "ALTER TABLE enrollments ALTER COLUMN tenant_id SET NOT NULL"),
    ("ix notif_recipients(recipient,read_at)",
     "CREATE INDEX IF NOT EXISTS ix_notif_recipients_user ON notification_recipients (recipient_id, read_at)"),

    # ── rbac: indexes + FK (ON DELETE SET NULL) on the role pointer ──────────
    ("ix school_authorities.rbac_role_id",
     "CREATE INDEX IF NOT EXISTS ix_school_authorities_rbac_role ON school_authorities (rbac_role_id)"),
    ("fk school_authorities.rbac_role_id",
     "ALTER TABLE school_authorities ADD CONSTRAINT fk_authorities_rbac_role "
     "FOREIGN KEY (rbac_role_id) REFERENCES rbac_roles(id) ON DELETE SET NULL"),

    # ── super-admin → admin → schools model ──────────────────────────────────
    # Which admin (school_authority) created/owns a school. Lets one admin own
    # many schools and the super-admin Tenants screen group schools per admin.
    ("tenants.owner_authority_id",
     "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS owner_authority_id UUID"),
    ("fk tenants.owner_authority_id",
     "ALTER TABLE tenants ADD CONSTRAINT fk_tenants_owner_authority "
     "FOREIGN KEY (owner_authority_id) REFERENCES school_authorities(id) ON DELETE SET NULL"),
    ("index tenants.owner_authority_id",
     "CREATE INDEX IF NOT EXISTS ix_tenants_owner_authority ON tenants (owner_authority_id)"),
    # An admin is created by the super-admin BEFORE they create any school, so
    # their tenant_id starts NULL (their active school is set on first creation).
    ("school_authorities.tenant_id nullable",
     "ALTER TABLE school_authorities ALTER COLUMN tenant_id DROP NOT NULL"),
    # Login is by phone+password; email is optional on admins.
    ("school_authorities.email nullable",
     "ALTER TABLE school_authorities ALTER COLUMN email DROP NOT NULL"),

    # ── rbac: 2nd per-org ceiling — which pages the ADMIN sees in their OWN
    #    sidebar (separate from the distributable authority/teacher/student cols).
    #    Default TRUE so existing orgs keep "admin sees everything".
    ("tenant_module_permissions.admin_enabled",
     "ALTER TABLE tenant_module_permissions ADD COLUMN IF NOT EXISTS admin_enabled BOOLEAN NOT NULL DEFAULT TRUE"),
]
