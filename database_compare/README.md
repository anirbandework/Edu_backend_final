# database_compare — migrations without Alembic

ORM models are the **source of truth**. `create_all` makes new tables; an
idempotent SQL list handles changes to existing tables. A diff tool compares
**local vs production** and generates the fix SQL. (Modeled on the
indusinfotechs_backend approach. Alembic is retired → `_alembic_disabled/`.)

## Files
- **`migrations.py`** — the ordered, idempotent `(label, sql)` list (`ALTER … IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, FKs).
- **`seeds.py`** — idempotent data seeds (super-admin from `.env`, per-organisation default RBAC roles, dev passwords).
- **`run_local_migration.py`** — `create_all` → migrations → seeds, on `DATABASE_URL`.
- **`run_production_migration.py`** — same on `PRODUCTION_DATABASE_URL` (no dev passwords; asks to confirm).
- **`check_schema_diff.py`** — introspects local vs prod, prints/saves the fix SQL.

## Everyday use (run from `edu_backend/`)
```bash
# set up / update LOCAL after changing a model
python -m database_compare.run_local_migration

# preview what production is missing
python -m database_compare.check_schema_diff           # or --save-sql

# apply to production
python -m database_compare.run_production_migration     # add --yes to skip prompt
```

## When you change/add a model
1. New **table** → `create_all` handles it automatically.
2. New **column / index / FK** on an existing table → add an idempotent line to `migrations.py`.
3. Run `run_local_migration`, then `check_schema_diff`, then `run_production_migration`.

`.env` needs `DATABASE_URL` (local) and, for prod, `PRODUCTION_DATABASE_URL`
(either `postgresql://` or `postgresql+asyncpg://` — the tools strip the async driver).
