"""Schema Diff Tool — compare LOCAL vs PRODUCTION schemas and emit fix SQL.

Checks tables, columns (type/nullable/default), indexes, and foreign keys, then
generates idempotent ALTER/CREATE statements to bring PRODUCTION in line with LOCAL.

Usage (from edu_backend/):
  python -m database_compare.check_schema_diff                 # full diff
  python -m database_compare.check_schema_diff -t students     # one table
  python -m database_compare.check_schema_diff --save-sql      # write schema_fix.sql
  python -m database_compare.check_schema_diff --prod <URL>    # override prod URL

Reads DATABASE_URL (local) and PRODUCTION_DATABASE_URL (prod) from .env.
"""
import os
import sys
import argparse
from datetime import datetime

from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv

load_dotenv()

# Tables that exist locally but should NOT be diffed against prod (add as needed).
IGNORE_TABLES: set[str] = set()


def sync_url(url: str | None) -> str | None:
    """Convert an async SQLAlchemy URL to a sync (psycopg2) one."""
    if not url:
        return url
    return url.replace("+asyncpg", "").replace("+psycopg", "")


def parse_args():
    p = argparse.ArgumentParser(description="Schema diff with SQL fix generation",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--local", help="Override local DATABASE_URL")
    p.add_argument("--prod", help="Override PRODUCTION_DATABASE_URL")
    p.add_argument("-t", "--table", help="Check only this table")
    p.add_argument("--save-sql", action="store_true", help="Save fix SQL to schema_fix.sql")
    p.add_argument("--verbose", action="store_true", help="Show matching tables too")
    return p.parse_args()


def connect(url: str, label: str):
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 15}, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"  connected — {label}")
        return engine
    except Exception as e:
        print(f"  ERROR cannot connect to {label}: {e}")
        sys.exit(1)


def get_columns(insp, table):
    cols = {}
    for col in insp.get_columns(table):
        rd = col.get("default")
        cols[col["name"]] = {"type": str(col["type"]), "nullable": col.get("nullable", True),
                             "default": str(rd).strip() if rd is not None else None}
    return cols


def get_indexes(insp, table):
    try:
        return {idx["name"]: idx for idx in insp.get_indexes(table)}
    except Exception:
        return {}


def get_fks(insp, table):
    try:
        return insp.get_foreign_keys(table)
    except Exception:
        return []


def normalize_type(t: str) -> str:
    t = t.upper().strip()
    for old, new in {"CHARACTER VARYING": "VARCHAR", "INTEGER": "INT", "BIGINT": "INT8",
                     "BOOLEAN": "BOOL", "DOUBLE PRECISION": "FLOAT8", "TEXT": "VARCHAR"}.items():
        if t.startswith(old):
            t = new + t[len(old):]
    return t


def diff_table(table, li, pi):
    lc, pc = get_columns(li, table), get_columns(pi, table)
    missing_cols = {c: lc[c] for c in lc if c not in pc}
    mismatches = {}
    for col in set(lc) & set(pc):
        d = {}
        if normalize_type(lc[col]["type"]) != normalize_type(pc[col]["type"]):
            d["type"] = (lc[col]["type"], pc[col]["type"])
        if lc[col]["nullable"] != pc[col]["nullable"]:
            d["nullable"] = (lc[col]["nullable"], pc[col]["nullable"])
        if d:
            mismatches[col] = d
    li_idx, pi_idx = get_indexes(li, table), get_indexes(pi, table)
    missing_idx = {k: li_idx[k] for k in li_idx if k not in pi_idx}
    lf = {(tuple(f["constrained_columns"]), f["referred_table"]): f for f in get_fks(li, table)}
    pf = {(tuple(f["constrained_columns"]), f["referred_table"]): f for f in get_fks(pi, table)}
    missing_fks = {k: lf[k] for k in lf if k not in pf}
    return {"local_cols": lc, "missing_cols": missing_cols, "mismatches": mismatches,
            "missing_idx": missing_idx, "missing_fks": missing_fks}


def has_diff(d):
    return any([d["missing_cols"], d["mismatches"], d["missing_idx"], d["missing_fks"]])


def gen_sql(table, d):
    out = []
    for col, info in sorted(d["missing_cols"].items()):
        nn = "" if info["nullable"] else " NOT NULL"
        df = f" DEFAULT {info['default']}" if info["default"] else ""
        out.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {info['type']}{nn}{df};")
    for name, idx in sorted(d["missing_idx"].items()):
        cols = ", ".join(idx.get("column_names", []))
        uniq = " UNIQUE" if idx.get("unique") else ""
        out.append(f"CREATE{uniq} INDEX IF NOT EXISTS {name} ON {table} ({cols});")
    for (cc, rt), fk in d["missing_fks"].items():
        rc = ", ".join(fk["referred_columns"])
        cn = fk.get("name") or f"fk_{table}_{'_'.join(cc)}"
        out.append(f"ALTER TABLE {table} ADD CONSTRAINT {cn} FOREIGN KEY ({', '.join(cc)}) REFERENCES {rt} ({rc});")
    return out


def run(args):
    local = sync_url(args.local or os.getenv("DATABASE_URL"))
    prod = sync_url(args.prod or os.getenv("PRODUCTION_DATABASE_URL"))
    if not local:
        print("ERROR: local DATABASE_URL not set"); sys.exit(1)
    if not prod:
        prod = sync_url(input("Enter PRODUCTION_DATABASE_URL: ").strip())
        if not prod:
            sys.exit(1)

    print("\n" + "=" * 76 + "\n  SCHEMA DIFF: LOCAL -> PRODUCTION\n" + "=" * 76)
    le, pe = connect(local, "LOCAL"), connect(prod, "PRODUCTION")
    li, pi = inspect(le), inspect(pe)
    lt = set(li.get_table_names()) - IGNORE_TABLES
    pt = set(pi.get_table_names()) - IGNORE_TABLES

    missing_tables = sorted(lt - pt)
    if missing_tables:
        print(f"\n  TABLES MISSING in production ({len(missing_tables)}):")
        for t in missing_tables:
            print(f"     - {t}   (run run_production_migration.py — create_all adds it)")

    all_sql, diffed = [], []
    for table in sorted((lt & pt) if not args.table else ({args.table} & lt & pt)):
        d = diff_table(table, li, pi)
        if has_diff(d):
            diffed.append(table)
            print(f"\n  ~ {table}: missing {len(d['missing_cols'])} cols, "
                  f"{len(d['missing_idx'])} idx, {len(d['missing_fks'])} fks, "
                  f"{len(d['mismatches'])} type/null mismatches")
            for col, dd in d["mismatches"].items():
                print(f"      ! {col}: {dd}")
            all_sql.extend(gen_sql(table, d))

    print("\n" + "=" * 76)
    print(f"  tables: local={len(lt)} prod={len(pt)} | with diffs={len(diffed)} | fix statements={len(all_sql)}")
    if missing_tables:
        print(f"  missing tables in prod: {', '.join(missing_tables)}")
    if all_sql:
        print("\n  -- FIX SQL (idempotent; run on PRODUCTION) --")
        for s in all_sql:
            print(f"  {s}")
        if args.save_sql:
            out = os.path.join(os.path.dirname(__file__), "schema_fix.sql")
            with open(out, "w") as f:
                f.write(f"-- generated {datetime.now():%Y-%m-%d %H:%M:%S}\n\n" + "\n".join(all_sql) + "\n")
            print(f"\n  saved -> {out}")
    else:
        print("\n  schemas match (no column/index/FK fixes needed).")
    le.dispose(); pe.dispose()
    print("=" * 76 + "\n")


if __name__ == "__main__":
    try:
        run(parse_args())
    except KeyboardInterrupt:
        print("\ninterrupted")
