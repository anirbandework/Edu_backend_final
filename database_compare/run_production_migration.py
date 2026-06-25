"""Sync the schema -> PRODUCTION (no Alembic).

  create_all (new tables)  ->  the SAME idempotent migrations as local  ->  safe seeds.

It does NOT seed dev passwords (production users set their own). It DOES ensure the
super-admin and the per-tenant default roles exist (both idempotent).

Run from edu_backend/:   python -m database_compare.run_production_migration [--yes]

Reads PRODUCTION_DATABASE_URL from .env (or prompts). Tip: run
`python -m database_compare.check_schema_diff` first to preview the drift.
"""
import os
import sys

import app.main  # noqa: F401 — registers every ORM model in Base.metadata
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from app.models.base import Base
from .check_schema_diff import sync_url
from .migrations import MIGRATIONS
from . import seeds

load_dotenv()


def run():
    assume_yes = "--yes" in sys.argv or "-y" in sys.argv
    url = sync_url(os.getenv("PRODUCTION_DATABASE_URL"))
    if not url:
        url = sync_url(input("Enter PRODUCTION_DATABASE_URL: ").strip())
    if not url:
        print("ERROR: no production URL"); sys.exit(1)

    host = url.split("@")[-1]
    print(f"\n⚠️  PRODUCTION migration -> {host}")
    if not assume_yes:
        if input("Type 'yes' to proceed: ").strip().lower() != "yes":
            print("aborted."); sys.exit(0)

    engine = create_engine(url, pool_pre_ping=True)

    Base.metadata.create_all(engine)
    print("  + create_all: ORM tables ensured")

    applied = skipped = 0
    for label, sql in MIGRATIONS:
        try:
            with engine.begin() as c:
                c.execute(text(sql))
            applied += 1
            print(f"  ok  {label}")
        except Exception as e:
            skipped += 1
            print(f"  !   skip {label}: {str(e).splitlines()[0][:90]}")
    print(f"  + migrations: {applied} applied, {skipped} skipped (already present)")

    with engine.begin() as c:
        print(seeds.seed_super_admin(c))
        print(seeds.seed_default_roles(c))

    engine.dispose()
    print("\nPRODUCTION migration complete.\n")


if __name__ == "__main__":
    run()
