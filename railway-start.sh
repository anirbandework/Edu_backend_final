#!/usr/bin/env bash
# Railway start command: ensure the schema + super-admin seed exist, then serve.
# Idempotent and runs ONCE in this start process (before gunicorn forks workers), so
# there's no multi-worker migration race. Fails fast if the migration can't complete.
set -euo pipefail

echo "[release] running production migration (schema + indexes + super-admin seed)…"
# In the container the prod DB is Railway's injected DATABASE_URL; fall back to it if
# PRODUCTION_DATABASE_URL isn't set explicitly.
PRODUCTION_DATABASE_URL="${PRODUCTION_DATABASE_URL:-${DATABASE_URL}}" \
  python -m database_compare.run_production_migration --yes

echo "[serve] gunicorn on 0.0.0.0:${PORT:-8000}"
exec gunicorn app.main:app \
  -w "${WEB_CONCURRENCY:-4}" -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8000}" \
  --max-requests 1000 --max-requests-jitter 100 --preload --timeout 120
