# assessment_management — authorization remediation plan

Generated from a per-endpoint multi-agent audit (72 endpoints, 10 routers). The module is
mounted under `/assessment` with `dependencies=AUTHED` (valid JWT required) but has **zero
principal-based authz or tenant scoping**: `tenant_id` / `teacher_id` / `student_id` /
`class_id` come from client query/body and are never verified against the JWT principal.
Impact: any authenticated user (incl. students) can read/write **across tenants** and
**impersonate** any user → grade tampering, answer-key disclosure, cross-user PII via IDOR,
cohort-analytics exposure to students, cross-tenant AI cost abuse.

**Status: COMPLETE.** All 10 routers remediated and verified (student→403 on staff endpoints;
students keep their own quiz/results/analytics access; RBAC 21/21):
- `ai_quiz_generation` → router-level `require_staff`.
- `assignment_grading` → role-gated (grade/submissions/download = staff); `submit-assignment` forces student_id=principal.
- `cbse_pdf_upload` → upload=staff; download/list tenant-scoped (cross-tenant IDOR closed).
- `cbse_simple_query` → tenant-scoped read.
- `cbse_curriculum` → writes=staff, read tenant-scoped; `subject.value` 500 bug fixed.
- `cbse_quiz_platform` → authoring=staff; attempt flows ownership-verified; answer-key gated; 2 P0s closed.
- `ai_student_analytics` → self-scoped students / staff cohort; `logger` NameError fixed.
- `ai_quiz_management` → derive teacher_id/student_id/tenant from principal throughout.
- `quiz_management` → full principal pattern + `submit_quiz_attempt` ownership guard (the worst P0).
- `ai_chat_integration` → left as-is (no tenant/user data; AUTHED is sufficient). Backlog: add rate-limiting.

The detail below is retained as the design reference. Remaining hardening is defense-in-depth at the
service layer (some services still filter by the now-principal-derived ids, which is correct, but a
couple do per-id ownership lookups worth tightening) — tracked as P2.

## The uniform fix per endpoint
1. Add `principal: Principal = Depends(<gate>)` (import `get_current_principal`/`require_staff`/`require_authority` + `Principal`).
2. **Derive `tenant_id = principal.tenant_id`** for non-super-admin; ignore/drop the client `tenant_id`.
3. For **principal-self** endpoints: force `student_id = principal.user_id` (non-super-admin); staff/super-admin may act on others within tenant.
4. For ownership writes (delete/publish/grade/status): verify the target row's `tenant_id == principal.tenant_id` (and teacher ownership) **server-side**, not from client ids.

## Gating plan

### require_staff (teacher + authority + super-admin) — students blocked
- quiz_management: `POST /quiz/topics`, `POST /quiz/questions`, `GET /quiz/topics/{id}/questions`, `POST /quiz/quizzes`, `GET /quiz/teachers/{id}/quizzes`, `GET /quiz/quizzes/{id}/results`, `DELETE /quiz/quizzes/{id}`, `PATCH /quiz/quizzes/{id}/status`, `POST /quiz/quizzes/create-with-questions`, `GET /quiz/grading/pending`, `POST /quiz/grading/{answer_id}`, `GET /quiz/grading/ready-to-publish`, `POST /quiz/results/publish`
- ai_quiz_generation (`/ai-quiz`): **DONE (router-level)** — generate-questions, batch-generate, suggest-assembly, grade-subjective, analyze-performance, enhanced-grading/{attempt_id}
- ai_quiz_management: `POST /create-quiz`, `GET /templates`, `POST /generate-from-template`, `GET /teacher/{id}/dashboard`, `GET /teacher/{id}/quizzes`, `GET /class-analytics/{quiz_id}/{class_id}`, `DELETE /quiz/{id}`, `PATCH /quiz/{id}/status`
- ai_student_analytics: `POST /generate-report`, `POST /intervention-analysis`, `POST /batch-student-analysis`
- cbse_curriculum: `POST /generate-chunks/{subject}`, `POST /generate-sample-paper/{subject}`, `POST /bulk-generate`
- cbse_quiz_platform: `POST /create-quiz`, `POST /add-question/{quiz_id}`
- cbse_pdf_upload: `POST /upload-paper/{subject}`
- assignment_grading: `GET /submissions/{assessment_id}`, `GET /download-submission/{id}`, `POST /grade-submission/{id}`  *(remove dead teacher_id param)*

### principal-self (student's own data; verify path/body user_id == principal.user_id, staff override)
- quiz_management: `POST /quiz/attempts/start`, `POST /quiz/attempts/submit` *(service loads attempt by id ALONE — must verify attempt.student_id==principal & tenant)*, `GET /quiz/students/{id}/available-quizzes`, `GET /quiz/students/{id}/results`
- ai_quiz_management: `GET /student/{quiz_id}`, `POST /start-attempt`, `POST /get-hint`, `GET /student/{id}/available-quizzes`, `GET /results/{attempt_id}`, `GET /student/{id}/history`
- ai_student_analytics: `POST /student-insights`, `POST /study-recommendations`, `POST /weakness-analysis`, `POST /exam-preparation`, `POST /performance-prediction`
- cbse_quiz_platform: `POST /start-attempt/{quiz_id}`, `POST /submit-answer` *(verify attempt ownership before write)*, `POST /complete-attempt/{attempt_id}`, `GET /results/{attempt_id}` *(returns PII+answers — owner/staff only)*
- assignment_grading: `POST /submit-assignment/{assessment_id}` *(force student_id=principal; validate file magic-bytes not just .pdf)*

### principal-read (any authenticated, tenant-scoped to principal)
- quiz_management: `GET /quiz/topics`, `GET /quiz/quizzes/{id}/student`
- cbse_quiz_platform: `GET /quiz/{id}` *(gate the `include_answers=true` branch behind require_staff)*
- cbse_curriculum: `GET /content/{subject}`  •  cbse_simple_query: `GET /content/{subject}`
- cbse_pdf_upload: `GET /download-paper/{id}` *(add `AND tenant_id=principal AND is_deleted=false` — currently no tenant filter = IDOR)*, `GET /papers/{subject}`
- ai_chat_integration: `POST /ai_chat`, `POST /ai_help`, `GET /ai_status`

### keep-open (health only)
- `GET /ai-quiz/health`, `GET /ai-quiz-management/health`, `GET /ai-learning/health`

## Top P0 highlights (fix first)
- `POST /quiz/attempts/submit` — loads attempt by id alone, no owner/tenant check → anyone overwrites/grades any attempt cross-tenant.
- `GET /cbse-quiz/results/{attempt_id}` — returns score + answers + student name (PII), no ownership check → IDOR leaks any student's grades.
- `POST /quiz/grading/{answer_id}` & `POST /grading/grade-submission/{id}` — student can self-assign marks (no role gate).
- `POST /quiz/results/publish`, `DELETE /quiz/quizzes/{id}`, `PATCH .../status` — destructive/lifecycle writes keyed on client-supplied ids.
- `GET /cbse-pdf/download-paper/{id}` — `WHERE id=:id` with no tenant filter → cross-tenant file IDOR.
- AI generate/batch endpoints — auto_save persists into client-supplied tenant_id (cross-tenant injection + cost abuse).

## Latent non-auth bugs noted
- `cbse_curriculum_routes`: `subject.value` assumes an enum but `subject` is a `str` → 500 on success path.
- `ai_student_analytics_routes` generate-report: uses `logger` without importing it → NameError.
- Several dead `teacher_id`/`student_id` query params now superseded by `principal.user_id`.
