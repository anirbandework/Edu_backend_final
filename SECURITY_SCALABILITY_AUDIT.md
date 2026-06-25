# EduAssist — Security, RBAC & Scalability Audit

**Scope:** Backend (`edu_backend`, FastAPI) + Frontend (`edu_assist_dynamic`, Flutter). Focus: how login & RBAC work for **all user types** (student, teacher, school authority, super admin) and readiness for **100k+ users (growing)**.
**Method:** 9 parallel auditor agents reading the actual code, each high/critical finding then independently re-verified against the source. 44 agents, ~1.4M tokens.
**Date:** 2026-06-23

---

## ⚖️ Verdict

**The system is a functional prototype, not production-ready. It must not hold real student data in its current state.**

There is **one root cause** from which almost every critical finding cascades:

> **There is no authentication and no authorization anywhere in the backend.** 280 route decorators, **zero** auth dependencies. "Login" = the client sends a user's UUID and the server trusts it. The RBAC tables (roles, permissions, page-access) are *data the UI reads to draw menus* — nothing on the server enforces them.

Consequence: **any anonymous internet client can read, modify, or delete every tenant's data** — student PII, grades, attendance, finances — by calling the public API. This does **not** improve with scale; it is total from user #1. At 100k users it means the full population (students, teachers, admins, all schools) is exposed.

### Severity tally (auditor-assigned, post-verification)
| Severity | Count |
|---|---|
| 🔴 Critical | 19 |
| 🟠 High | 16 |
| 🟡 Medium | 6 |
| 🟢 Low/Info | 5 |

Verification confirmed every critical. Only **CORS `*`** was downgraded (high→medium, as secondary to the no-auth issue); two frontend items were *upgraded* to critical.

---

## 1. Authentication & Login (all user types) — 🔴 CRITICAL

| # | Finding | Evidence |
|---|---|---|
| 1.1 | **No credential of any kind.** Login is `GET /api/auth/user-profile/{user_id}` → looks up the UUID in `school_authorities` → `teachers` → `students` and returns the full profile + permissions. No password / OTP / token is ever requested, checked, or issued — for any role. Super-admin endpoints take the acting admin's id as a *query param* (`granted_by`) with no check. | `auth_rbac/routers/auth.py:10-20`, `auth_rbac/services/auth_service.py:117-142,243-273,374-406`, `super_admin_router.py:16-26` |
| 1.2 | **No session/JWT issued or verified.** `jwt_secret_key` is declared (`config.py:9`) but never used. The only middleware adds an `X-Process-Time` header. Identity on every request = whatever `{user_id}`/`{tenant_id}` the caller puts in the URL. Nothing to revoke, expire, or rotate. | `config.py:9`, `main.py:141-171` |
| 1.3 | **Anyone can be anyone — and UUIDs are mass-leaked.** The login key (the row's primary-key UUID) is returned in plaintext by **unauthenticated list endpoints** (`GET .../students/`, `.../teachers/`, `.../tenant/{id}`, page size up to 100). An attacker pages the list, harvests every UUID, then "logs in" as each. The credential is *published by the API itself.* | `student_management/routers/student.py:100-163,124,267`, `teacher_management/routers/teacher.py:101-167`, `school_authority/routers/school_authority.py:72-143` |

**Fix (P0):** Real credentials (Argon2/bcrypt password and/or OTP/SSO) → issue a signed, expiring token (JWT or opaque Redis session) at login → verify it on every request via a shared `Depends(get_current_principal)`. Stop returning the primary-key UUID as the de-facto login key.

---

## 2. Authorization enforcement — 🔴 CRITICAL

**Of the ~247 endpoints in the 12 resource routers, exactly zero enforce authorization.** The only `Depends` values are `Depends(get_db)` (×241) and one rate-limiter on an assessment route. Routers are mounted with no `dependencies=[...]`.

| # | Finding | Evidence |
|---|---|---|
| 2.1 | **Every resource endpoint is open** (read + mutate), across students, teachers, classes, enrollment, attendance, timetable, notifications, exams, assessments, tenants, chat. | `main.py:195-215`, `tenant_management/routers/tenant.py`, `student_management/routers/student.py` |
| 2.2 | **`DELETE /tenants/{id}?hard_delete=true` permanently destroys any school** — no caller check. Plus `bulk_delete_tenants` (up to 100 ids). A platform-wipe primitive. | `tenant_management/routers/tenant.py:429-454,773-794` |
| 2.3 | **Student bulk mutations** (delete / grade-change / promote / status / sections) callable by anyone; `tenant_id` taken from the request body → cross-tenant grade tampering & cohort deletion. | `student_management/routers/student.py:435-451,453-465,509` |
| 2.4 | **Notification `/send` impersonation:** `sender_id` is client-supplied and only checked for *existence*, not identity. Anyone can blast `all_students`/`all_teachers` as any teacher/authority. | `notification_management/routers/notifications.py:104-110,55-90,118-119` |
| 2.5 | **IDOR on assignments/marks:** download any student's submitted PDF by `submission_id`; write marks with a client-supplied `teacher_id`/`marked_by`. | `assessment_management/routers/assignment_grading_routes.py:91-135,11-35`, `exam_management/routers/exam_management.py:75-90` |
| 2.6 | **CORS `*`** with all mutating methods — any website can script these calls from a visitor's browser. (Verifier: medium, secondary to no-auth.) | `main.py:175-191` |

**Fix (P0):** Global router-level auth dependency; derive `tenant_id` and identity from the verified token, never from client input; per-endpoint role/ownership checks; remove `hard_delete` from the API surface or gate behind strict super-admin + audit log.

---

## 3. Multi-tenant isolation — 🔴 CRITICAL / 🟠 HIGH

**There is no tenant isolation.** Every `tenant_id` used in a query is trusted from the client (query/path/body); by-id lookups don't filter by tenant at all.

| # | Finding | Evidence |
|---|---|---|
| 3.1 | **By-id student endpoints not tenant-scoped** — read/edit/delete any student's full PII (incl. `financial_info`, `health_medical_info`) by GUID. Base service does `where(id==:id)` with no tenant filter. | `student_management/routers/student.py:186-265`, `services/base_service.py:15-18` |
| 3.2 | **Tenant API fully open** — list all schools, read/modify/destroy any, including financials/charges. The all-schools listing hands attackers the full `tenant_id` catalog. | `tenant_management/routers/tenant.py:73-151,315-473` |
| 3.3 | **Class, attendance, notification by-id endpoints** resolve by id with no tenant scoping; some *infer* the auth tenant from the target object itself. | `class_management/routers/class_management.py:156-218,461-663`, `attendance_management/routers/attendance.py:117-251` |
| 3.4 | **List endpoints leak all-tenant data** when `tenant_id` is omitted (filter is `if tenant_id:` — optional). | `student_management/services/student_service.py:151-175` |
| 3.5 | **Bulk writes trust body `tenant_id`** for the `WHERE` clause → one request can wipe a competing school's student body. | `student_management/services/student_service.py:441-498,602-637` |
| 3.6 | **`/debug/*` endpoints mounted in production** dump notifications/recipients/students per tenant; one runs **DDL** (`setup-archive-column`). | `notification_management/routers/notifications.py:480-528,610-652,847-882` |

**Fix (P0/P1):** Server-derived tenant scope on **every** query (`WHERE ... AND tenant_id = :auth_tenant`); 404 on mismatch; enforce at the service layer (ideally Postgres Row-Level Security as defense-in-depth); delete `/debug/*` from production builds.

---

## 4. RBAC subsystem — advisory only + correctness bugs — 🔴/🟠/🟡

The RBAC design (roles, `user_roles`, `page_permissions` with 6 CRUD flags, `tenant_page_access` super-admin grants) is reasonable **as a model**, but it is a **UI-menu system, not an access-control system.**

| # | Finding | Sev | Evidence |
|---|---|---|---|
| 4.1 | Effective permissions are computed and **returned to the client but never enforced** server-side. `grep can_create\|can_edit\|...` outside `auth_rbac` → 0 matches. | 🔴 | `auth_service.py:38-115` |
| 4.2 | **user-profile leaks full PII + permissions** by UUID, no authz (health/financial/parent/disciplinary JSON included). | 🔴 | `auth_rbac/routers/auth.py:10-20`, `auth_service.py:374-406` |
| 4.3 | **Page-id namespaces don't match.** Defaults use `'dashboard'`/`'profile'`; `PAGES_REGISTRY` uses `'admin-dashboard'`/`'teacher-profile'`; `/available-pages` uses bare `'classes'`. Permission resolution is incoherent. | 🟠 | `auth_service.py:44,60`, `constants/pages_registry.py:11-48`, `super_admin_router.py:68-84` |
| 4.4 | Teacher/student role-page resolution in `user_access.py` is a **TODO stub returning `[]`**. | 🟡 | `auth_rbac/routers/user_access.py` |
| 4.5 | `user_roles` uniqueness is **global (`user_id` only)**; role/permission queries aren't tenant-scoped → cross-tenant resolution risk. | 🟡 | `auth_rbac/models/role_management` |
| 4.6 | Dead code (`check_tenant_page_access`, `get_role_permissions_filtered_by_tenant` never called); `custom_permissions` stored but never interpreted. | 🟢 | — |

**Fix:** Once auth exists, resolve `PagePermission` server-side and assert the needed flag per route. Unify the page-id namespace with a startup assertion. Make `user_roles` unique per `(user_id, tenant_id)`. Finish/remove the stubs.

---

## 5. Frontend identity & gating — 🔴 CRITICAL

| # | Finding | Sev | Evidence |
|---|---|---|---|
| 5.1 | **Login is a UUID textbox** (format regex only, no secret). | 🔴 | `school_selection_screen.dart:1186,1197-1208` |
| 5.2 | **`role` and `tenantId` are plaintext, editable URL query params** → privilege escalation & cross-tenant access from the address bar. `userRole` defaults to `'tenant_manager'` if absent. | 🔴 | `school_selection_screen.dart:1333-1339`, `app_router.dart:44,46,61-183` |
| 5.3 | **No route guards** — every role's screens reachable by URL; GoRouter has no `redirect`/`refreshListenable`. | 🔴/🟠 | `app_router.dart:28-198` |
| 5.4 | **Gating is a hardcoded `switch(userRole)`**; the app **never calls the backend RBAC endpoints** (`/user/{id}/access`). Role is never validated against the looked-up user's real role. | 🔴 | `navigation_sidebar.dart:164-403`, `main_layout.dart:360-367` |
| 5.5 | **No `Authorization` header on any API call** (only a commented placeholder). | 🟠 | `app_router.dart:172-176`, `class_service.dart:14,25` |
| 5.6 | **Hardcoded LLM key in client** (`_apiKey = 'YOUR KEY'`, currently placeholder; a real Gemini key appears in frontend git history — commit "KEY HIDDED (GEMINI)" — treat as compromised, rotate). | 🟠 | `ai_service.dart:6,35` |
| 5.7 | Session is plaintext in-memory statics, no expiry/integrity; PII printed to logs & success messages. | 🟡/🟢 | session singletons |

**Fix:** The client is cosmetic — all enforcement must be server-side. After real login: store the token, attach it via one shared HTTP interceptor, build menus from server-returned permissions, add a GoRouter `redirect` requiring a valid session. Proxy LLM calls through the backend.

---

## 6. Scalability at 100k+ users — 🔴/🟠

Schema indexing is good in some domains (exam, auth_rbac, page_permissions use composite indexes) — but the **highest-volume tables and hottest paths are not tuned**.

| # | Finding | Sev | Evidence |
|---|---|---|---|
| 6.1 | **Connection pools unconfigured** (default ~15/engine) with **two engines** under `--preload` Gunicorn fork. Ceiling ~120 conns; `--preload` fork-sharing of asyncpg connections causes non-deterministic errors under concurrency. | 🔴→🟠 | `core/database.py:15-43`, `Dockerfile:85` |
| 6.2 | **Hot multi-column queries have only single-column indexes** (attendances, students, notification_recipients) — no composite index matching the `WHERE`. Tens of millions of attendance rows → scans. | 🟠 | `attendance/models/attendance.py:45-101`, `student/models/student.py:7-44` |
| 6.3 | **OFFSET/LIMIT + separate `COUNT(*)` per page** — deep pages and large tenants degrade linearly. | 🟠 | `services/base_service.py:20-94` |
| 6.4 | **`bulk_mark_attendance` is a per-row SELECT-then-INSERT/UPDATE loop** holding one connection — should be a single `INSERT ... ON CONFLICT`. | 🟠 | `attendance/services/attendance_service.py:158-274` |
| 6.5 | **Notification fan-out uses non-sargable JSONB joins** (`assigned_teachers`) + `->>` projections, no GIN index — re-scans teachers per class. | 🟠 | `notification/services/notification_service.py:366-369,552-565` |
| 6.6 | **Login costs 5–7 sequential DB queries with no caching**; 3-table lookup is ordered authority→teacher→student (backwards for students, the dominant user). | 🟡 | `auth_service.py` |
| 6.7 | **Rate limiter is an in-process `dict`** — doesn't work across the 4 Gunicorn workers and grows unbounded. | 🟡 | `core/rate_limiter.py:7-28` |

**Fix:** Put **PgBouncer** (transaction mode) in front of Postgres; explicitly size pools so `(pool+overflow) × engines × workers < max_connections`; drop `--preload` or recreate engines post-fork; add composite indexes matching query shapes; keyset pagination + cached/approx counts for hot lists; set-based bulk upserts; normalize `class_teachers` into a join table (or GIN index); cache resolved permissions/roles in Redis; move rate-limiting to Redis.

---

## 7. Other security posture — 🟡

| # | Finding | Evidence |
|---|---|---|
| 7.1 | **Error handler leaks internals** — returns `f"Internal server error: {str(exc)}"` to the client. | `main.py:134` |
| 7.2 | **f-string SQL construction** in several services (`text(f"...")`) — audit each for client-input interpolation (injection surface). | `teacher_service.py:282`, `notification_service.py:144`, `enrollment_service.py:966-999`, `attendance_service.py:393` |
| 7.3 | **Secrets in plaintext `.env`** (AWS, JWT, Perplexity). Good: `.env` **is** gitignored (not committed). Still: rotate the frontend Gemini key that reached git history; move secrets to a secret manager for prod. | `.env`, `.gitignore:2-4` |

---

## 🗺️ Remediation roadmap (priority for a 100k-user multi-tenant SaaS)

**P0 — do before any real data (security-critical, blocks launch):**
1. Real authentication: credential + hashed storage + signed expiring token at login.
2. Global `get_current_principal` auth dependency on every router; derive identity **and** `tenant_id` from the token, never from client input.
3. Tenant-scope every query; 404 on mismatch; ideally Postgres RLS as a backstop.
4. Remove `/debug/*` and `hard_delete` from the production API; add audit logging on destructive ops.
5. Stop returning the PK UUID as the login key; lock down list/by-id endpoints.

**P1 — correctness & defense-in-depth:**
6. Enforce `PagePermission` flags server-side; unify the page-id namespace; finish/remove RBAC stubs; `user_roles` unique per `(user_id, tenant_id)`.
7. Frontend: token interceptor, server-driven menus (`/user/{id}/access`), GoRouter `redirect`, proxy LLM calls, stop trusting URL `role`/`tenantId`.
8. Restrict CORS to known origins; stop leaking `str(exc)`; audit f-string SQL.

**P2 — scale hardening (before traffic ramps):**
9. PgBouncer + explicit pool sizing + fix `--preload` fork issue.
10. Composite indexes on hot paths; keyset pagination + approx counts.
11. Set-based bulk upserts; normalize `class_teachers`; Redis-cache permissions; Redis rate limiting.

---

## Notes on coverage
- 7 of 9 audit dimensions returned full structured findings; 2 (`security-crosscutting`, `scale-auth-rbac`) hit transient API errors mid-run — their content is reconstructed here from direct verification (§6.6–6.7, §7) and overlapping findings in other dimensions.
- Every 🔴/🟠 finding above was independently re-read and confirmed by a second agent (or by direct grep in this session). CORS was the only severity adjustment (down to 🟡).
