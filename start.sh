#!/usr/bin/env bash
#
# EduAssist BACKEND launcher
# ---------------------------------------------------------------------------
# One command to bring the whole backend up:
#   1. ensures the NATIVE Postgres + Redis (Homebrew services) are running
#   2. activates the Python venv (venv) automatically
#   3. runs the FastAPI server (uvicorn) on http://localhost:8000
#
# IMPORTANT: this app uses the native brew services (postgresql@14 + redis) that
# hold the real data. Do NOT also run a Docker Postgres on 5432 — "localhost"
# splits across ::1/127.0.0.1 and connections land in the wrong database.
#
# Usage:   ./start.sh            # start everything (Ctrl+C stops the API)
# ---------------------------------------------------------------------------

# Always run from the directory this script lives in
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BACKEND_DIR" || exit 1

echo "==> EduAssist backend  ($BACKEND_DIR)"

# 1) Ensure native Postgres + Redis (Homebrew) are running
if ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
  echo "==> Starting Postgres (brew services postgresql@14)..."
  brew services start postgresql@14 >/dev/null 2>&1 || true
fi
if ! (redis-cli -h 127.0.0.1 ping >/dev/null 2>&1); then
  echo "==> Starting Redis (brew services redis)..."
  brew services start redis >/dev/null 2>&1 || true
fi

printf "==> Waiting for Postgres"
for _ in $(seq 1 30); do
  if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then echo " — ready"; break; fi
  printf "."; sleep 1
done

# 4) Free port 8000 if a previous API instance is still running
if lsof -ti:8000 >/dev/null 2>&1; then
  echo "==> Port 8000 busy — stopping previous API instance..."
  lsof -ti:8000 | xargs kill 2>/dev/null || true
  sleep 1
fi

# 5) Activate the venv and launch the API
# NOTE: this venv's bundled `activate` has a stale absolute path baked in
# (the project was moved from /Users/anirbande/Desktop/edu_backend), which
# breaks PATH. So we set VIRTUAL_ENV to the real location and invoke the
# venv's python binary directly — robust regardless of where the repo lives.
echo "==> Activating venv (venv) and starting FastAPI..."
export VIRTUAL_ENV="$BACKEND_DIR/venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

echo "==> API:     http://localhost:8000"
echo "==> Swagger: http://localhost:8000/docs"
echo "==> (Ctrl+C to stop the API)"
exec "$VIRTUAL_ENV/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
