"""Set up / migrate the LOCAL database (no Alembic).

  create_all (new ORM tables)  ->  idempotent column/index/FK migrations  ->  seeds.

Run from edu_backend/:   python -m database_compare.run_local_migration
"""
import os
import sys

import app.main  # noqa: F401 — registers every ORM model in Base.metadata
# super_admins is only imported lazily inside login_service, so app.main alone
# does not register it in Base.metadata — import it explicitly so create_all builds it.
from app.auth_rbac.models.super_admin import SuperAdmin  # noqa: F401
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from app.models.base import Base
from .check_schema_diff import sync_url
from .migrations import MIGRATIONS
from . import seeds

load_dotenv()


def run():
    url = sync_url(os.getenv("DATABASE_URL"))
    if not url:
        print("ERROR: DATABASE_URL not set"); sys.exit(1)
    print(f"\nLOCAL migration -> {url.split('@')[-1]}\n")
    engine = create_engine(url, pool_pre_ping=True)

    # 1) create any NEW tables from the ORM models
    Base.metadata.create_all(engine)
    print("  + create_all: ORM tables ensured")

    # 2) idempotent column/index/FK migrations (each in its own tx)
    applied = skipped = 0
    for label, sql in MIGRATIONS:
        try:
            with engine.begin() as c:
                c.execute(text(sql))
            applied += 1
        except Exception as e:
            skipped += 1
            print(f"  ! skip [{label}]: {str(e).splitlines()[0][:90]}")
    print(f"  + migrations: {applied} applied, {skipped} skipped (already present)")

    # 3) seeds (local gets dev passwords too)
    with engine.begin() as c:
        print(seeds.seed_super_admin(c))
        print(seeds.seed_default_roles(c))
        print(seeds.seed_dev_passwords(c))

    engine.dispose()
    print("\nLOCAL migration complete.\n")


if __name__ == "__main__":
    run()
