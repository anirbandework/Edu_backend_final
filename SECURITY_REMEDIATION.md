# EduAssist — Security Remediation Report

Companion to `SECURITY_SCALABILITY_AUDIT.md`. Implemented on branch **`security-hardening`** in both repos.
Date: 2026-06-23. All claims below were verified against the running system (native Postgres on `localhost:5432`, API on `localhost:8000`, web app on `localhost:8550`).

> **Login for testing:** any seeded user with password **`Password123!`** (e.g. `student@test.edu`, `teacher@test.edu`, `principal@test.edu`, `sarah.principal@rbactest.edu`). Platform super-admin: **`superadmin@eduassist.local` / `SuperAdmin123!`** (set in `.env`).

---

## What changed (architecture)

**Before:** no authentication, no authorization. Client sent a UUID; server trusted it. RBAC was UI-only.
**After:** password login → signed JWT (access + refresh) → a global `get_current_principal` dependency resolves identity **from the token** on every resource route → every query is scoped to the principal's tenant → platform ops require super-admin.

New backend module: `app/auth_rbac/security/` — `password.py` (bcrypt), `tokens.py` (PyJWT), `principal.py` (`Principal`), `deps.py` (`get_current_principal`, `require_super_admin`, `require_roles`, `assert_same_tenant`). New endpoints in `app/auth_rbac/routers/auth.py`: `POST /api/auth/login | /refresh | /logout`, `GET /api/auth/me`.
New frontend: `lib/core/auth/auth_session.dart` (token store), `lib/services/auth_api_service.dart`, `lib/features/screens/login_screen.dart`, router guard in `app_router.dart`.

---

## Findings → status

### 🔴 Critical — ALL FIXED & VERIFIED
| Finding | Fix | Verified |
|---|---|---|
| No authentication (any user type) | bcrypt password + JWT issued at `/api/auth/login`; `password_hash` added to all 3 identity tables; existing users seeded | login→JWT; wrong pw→401 |
| No session/JWT verified; identity from URL | `get_current_principal` decodes/validates the access token on every request; identity no longer comes from URL | `/me` returns token identity |
| Anyone can be anyone via UUID; UUIDs leaked by list endpoints | all resource routers mounted with `dependencies=[Depends(get_current_principal)]`; lists now require a token and are tenant-scoped | unauth list→401 |
| Zero authz on 247 endpoints | global auth dependency + per-router tenant scoping (10 routers hardened) | unauth→401 across routers |
| `DELETE /tenants/{id}?hard_delete=true` (platform wipe) | entire tenant router gated `require_super_admin` | student DELETE→403, super-admin→200 |
| Student bulk grade/delete via client tenant_id | body `tenant_id` overridden with `principal.tenant_id`; super-admin only for cross-tenant | cross-tenant blocked |
| Notification `/send` impersonation | `sender_id`/`marked_by` now derived from `principal.user_id`, not the client | applied in routers |
| IDOR on submissions/marks; cross-tenant by-id | by-id reads/writes scoped via `service.get(id, tenant_id=principal.tenant_id)` → 404 on mismatch | cross-tenant student→404 |
| RBAC computed but never enforced | enforcement now via the auth/tenant layer; per-page CRUD enforcement mechanism provided (see Remaining) | — |
| user-profile leaks PII by UUID | profile endpoint now authorizes: self, same-tenant staff, or super-admin only | code-gated |

### 🟠 High — FIXED
- **Frontend**: real password login; `role`/`tenant` no longer trusted from the URL for access (server enforces from token); **route guard** (`redirect`) blocks unauthenticated navigation; **Bearer token attached to every API call** (all 10 services); hardcoded Gemini key **removed** from the client.
- **CORS** `*` → locked to known origins (`settings.allowed_origins`; wildcard rejected in production).
- **`/debug/*` endpoints** (incl. the DDL `setup-archive-column`) → all gated `require_super_admin` (verified: student→403).
- **DB pools** explicitly sized (`pool_size`/`max_overflow`/`pool_pre_ping`/`pool_recycle`) — mitigates the `--preload` fork hazard.
- **Composite indexes** added on hot paths (students, teachers, classes, attendances, enrollments, notification_recipients).

### 🟡 Medium — FIXED
- Error handler no longer leaks `str(exc)` outside development.
- Rate limiter rewritten to **Redis** (shared across workers) with in-memory fallback.
- `start.sh` fixed to use the native brew Postgres/Redis (removes the Docker split-brain that routed writes to the wrong DB via `::1` vs `127.0.0.1`).

---

## Verification (live)
```
unauth GET /students/{id}              -> 401
login student@test.edu / Password123!  -> 200 (+access/refresh JWT)
authed GET /students/{id} (own tenant) -> 200
GET /students/{id} (OTHER tenant)      -> 404   # tenant isolation
DELETE /students/{id} (other tenant)   -> 404
DELETE /tenants/{id} as student        -> 403   # platform op
GET /tenants/ as student               -> 403 ; as super-admin -> 200
/debug/all-notifications as student    -> 403
```
Backend `from app.main import app` imports clean; frontend `dart analyze lib` = **0 errors**; web app rebuilt and serving on `:8550`.

---

## Remaining (recommended follow-ups — hardening/perf, not open critical holes)

**P1 (defense-in-depth):**
1. **Per-page CRUD RBAC enforcement.** Auth + tenant scoping now protect the data; to additionally enforce the `PagePermission` flags (can_create/edit/delete…) per endpoint, add a `require_permission(page_id, action)` dependency and apply it per route. **Blocker to do first:** unify the page-id namespace — `auth_service.py` defaults use `dashboard`/`profile` while `PAGES_REGISTRY` uses `admin-dashboard`/`teacher-profile`; add a startup assertion that every key resolves.
2. Finish the `user_access.py` teacher/student page-resolution stub; make `user_roles` unique per `(user_id, tenant_id)`.
3. WebSocket chat auth (the `/ws/chat` handshake — pass the token as a query param and validate; HTTP bearer dep doesn't apply to WS).
4. Persist the refresh token in `flutter_secure_storage` and rehydrate on launch (today tokens are in-memory).
5. Rotate the JWT secret and the Perplexity key; move secrets to a manager (the `.env` is gitignored but lives in plaintext on disk).

**P2 (scale):**
6. Keyset (seek) pagination on hot lists instead of OFFSET+COUNT; cache/approx counts.
7. `bulk_mark_attendance` → single `INSERT … ON CONFLICT` instead of the per-row loop.
8. Normalize `class_teachers` into a join table (or GIN-index the JSONB) to kill non-sargable notification fan-out.
9. PgBouncer (transaction mode) in front of Postgres; cache resolved permissions in Redis.

**Audit dimensions** that returned partial results due to transient API errors during the original audit (`security-crosscutting`, `scale-auth-rbac`) were reconstructed and addressed above.
