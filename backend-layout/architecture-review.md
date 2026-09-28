# Rafiqi backend architecture review

**Reviewed:** 2026-09-25
**Backend:** `VoiceTrace/rafiqi-api` `main`, commit `ad0717cefe31da9b797e1234d94f887a15fde07a` (verified against `origin/main`)
**Scope authority:** backend `docs/artifact.md` (Revision 2), backend `docs/review-companion.md`, frontend `docs/RAFIQI_PRODUCT_AND_DESIGN_REFERENCE.md`, approved frontend Board 41 and the other local boards cited below. Backend `AGENTS.md` and `.claude/STATUS.md` define architecture conventions and open decisions.
**Method:** source, model, migration, API, test and documentation review; application OpenAPI inspection; local test run. This is a source review, not a deployment, live-data, penetration, or legal audit.

## Executive assessment

The backend is a coherent **foundation and approved review-companion demo**. Its review flow has persisted sessions, bounded transitions, bilingual catalog content, idempotency keys, attempt evidence, concept mastery, completion snapshots and tests. It is **not yet the complete MVP v1 backend** described by Revision 2's `Study → Profile → Prep + Homework → Study` loop. The A/B/E domains and the links between them have not been implemented. That difference is deliberate for Board 41's narrow mock slice, but must be explicit in delivery status and product claims.

**Architectural disposition:** suitable for continued internal demo and incremental development; not ready to support real school data or a full MVP launch. Prioritize the concrete access-control, token-rotation and file-handling findings below before broad rollout, then settle the A8 data-handling decisions and build the missing domains in dependency order. The architecture can evolve in place; no rewrite or microservice split is justified by current evidence.

## Findings, in priority order

### P0 — Deactivated users retain access with existing JWTs

`app/api/deps.py:24–67` trusts `sub`, `school_id` and `role` from a signed JWT for all protected routes without loading the current account. `app/services/user.py:175–190` only changes `is_active`; `app/services/auth.py:72–85` checks that flag during refresh, and logout only revokes a refresh token. A deactivated account can continue to use its old access token until the configured 30-minute expiry. The backend status file explicitly acknowledges this, but it is a launch-critical decision when a school must promptly remove access to student records. **Recommendation:** define revocation latency with the product/privacy owner; if immediate removal is required, check active status and current role/school at the authorization boundary or use a revocable session/version cache. Add an end-to-end deactivation test. Avoid claiming that logout or deactivation immediately ends access. Evidence: `app/core/config.py:13`, `app/api/deps.py`, `app/services/auth.py`, `.claude/STATUS.md` Open Decisions.

### P0 — Refresh-token rotation can issue two successors under concurrency

`app/services/auth.py:70–85` reads the refresh-token row, checks `revoked_at`, commits revocation, then issues its replacement in a second transaction. There is no row lock or conditional update. Two near-simultaneous refreshes can both observe the token as unused and each mint a successor. A failure after the revocation commit can also strand the client without the new token. **Recommendation:** consume the old token exactly once in one transaction (`SELECT ... FOR UPDATE` or conditional `UPDATE ... WHERE revoked_at IS NULL ... RETURNING`), insert its successor before one commit, and test simultaneous refreshes in PostgreSQL. Continue storing only hashes and preserving rotation, which align with [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html). Evidence: `app/services/auth.py:27–38,60–85`; `app/models/refresh_token.py`.

### P0 — A8 governance is unresolved despite sensitive attempt and mastery storage

The approved Revision 2 plan calls for decisions on consent, retention, deletion, transfer, disclosure and performance-data use before finalizing A1/D4 and exposing parent-facing output (`docs/artifact.md:63–76`). The current schema already stores answer text, wrong-answer taxonomy, inferred mastery, profile traits and conversation references. There is no visible consent record, retention/deletion workflow, access audit, export workflow, or documented school-transfer policy in `app/`, migrations, or the status document. This is an **unresolved product/governance gate**, not a finding that the current demo itself violates a law. **Recommendation:** produce the written A8 data-handling decision with the school/privacy owner, then derive schema changes, retention jobs, role permissions, audit events and verified deletion/export behavior before real student data. Do not treat profile and mastery as formal grades. Evidence: `docs/artifact.md`, `.claude/STATUS.md`, `app/models/profile.py`, `app/models/review.py`.

### P1 — Uploaded avatars are accepted by a spoofable header and served publicly

`app/services/user.py:111–138` chooses the extension from `UploadFile.content_type`, reads the whole upload, removes the previous file and writes the new bytes before the database commit. It does not inspect image bytes or verify that decoding succeeds. `app/main.py:129` exposes `/media` through a public static mount, so possession of a known URL is enough to read an avatar. A failed commit can leave file state inconsistent with `avatar_url`. **Recommendation:** verify file signatures and decode/re-encode accepted images, enforce upload/request size before full buffering, write to a temporary object, commit URL metadata, then atomically promote or compensate; define whether school avatars are intended to be public. OWASP also advises against trusting a claimed `Content-Type`: [File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html). Evidence: `app/services/user.py:111–149`, `app/main.py:129`, `tests/test_avatar.py` (uses small fake bytes).

### P1 — Tenant isolation relies entirely on application filters

Review services correctly filter owned sessions, attempts, summaries and mastery by school and student. Catalog rows are intentionally global. However, `school_id`, `student_id` and `session_id` on evidence tables have independent foreign keys: the database does not enforce that they belong to the same school or that an attempted lesson matches its session. Nor are row-level-security policies defined. A future service query or write can therefore cross-associate data despite the project rule that school isolation is mandatory. **Recommendation:** centralize tenant-aware access patterns, add composite ownership constraints where practical, and consider PostgreSQL row-level security as a second barrier before real multi-school data. Extend isolation tests to every new domain. Evidence: `app/models/review.py`, initial and review migrations, `app/services/review.py:244–265,345–375`; backend `AGENTS.md` multi-tenancy rule.

### P1 — Several auth/user services break the project's own layer contract

Backend `AGENTS.md` requires thin routes, domain exceptions in services, and Pydantic/plain-value service results. `app/services/user.py` and `app/services/auth.py` import and raise FastAPI `HTTPException`; user services return ORM `User` objects to routes, which perform Pydantic conversion. `app/api/routes/auth.py:83–97` does not declare `response_model` for logout. The review routes mostly follow the intended separation, though `create` branches on the `created` flag to set HTTP status. **Recommendation:** introduce domain exceptions and response schemas at the service boundary, then enforce the convention with a small architecture test or static check. This matters as soon as user/auth operations are reused by jobs or other transports. Evidence: `AGENTS.md` and `.claude/skills/python-architecture/SKILL.md`; `app/services/user.py`, `app/services/auth.py`, `app/api/routes/users.py`, `app/api/routes/auth.py`.

### P1 — The frontend auth contract does not match backend refresh and signup contracts

The local frontend integration at `src/features/auth/server/auth-api.ts` sends `{refreshToken}` and expects camelCase fields including `accessTokenExpiresAt`, while the backend accepts `{refresh_token}` and returns `{access_token, refresh_token, token_type}`. It calls `/auth/register`, `/auth/forgot-password`, `/auth/reset-password` and `/auth/verify-email`, none of which are mounted in backend `app/main.py`. Its error parser looks for top-level `code`, whereas backend exceptions use `detail.error.code`. The frontend currently has unresolved merge conflicts and an older checked-out commit, so these are **integration risks observed in its working tree**, not a claim that a stable frontend release is broken. **Recommendation:** establish a single versioned API contract, generate or validate types from backend OpenAPI, add a frontend/backend contract test, and reconcile the frontend branch before interpreting it as shipped behavior. Evidence: frontend `src/features/auth/server/auth-api.ts`, backend `app/schemas/auth.py`, `app/api/routes/auth.py`, `app/main.py`.

### P1 — Test and deployment gates do not protect the database path

The local run yielded **69 passed, 8 skipped**; the skipped tests are the PostgreSQL API/concurrency and migration tests because `REVIEW_TEST_DATABASE_URL` was not configured. `.github/workflows/docs.yml` only installs dependencies, exports OpenAPI and deploys docs; it has no unit, integration, migration, lint, secret/config or contract gate. `/health` returns a constant process response without checking database readiness. **Recommendation:** add CI with a disposable PostgreSQL service and execute all tests and migration upgrade/downgrade checks, verify OpenAPI contract compatibility, and distinguish liveness from readiness. Reject default signing keys in production. Evidence: test output of 2026-09-25, `tests/test_review.py:117–119`, `tests/test_review_catalog_migration.py:23–25`, `.github/workflows/docs.yml`, `app/main.py:132–135`, `app/core/config.py:11`.

### P2 — Session storage is correct for a small demo, with clear growth limits

`review_sessions.content` snapshots lesson JSON and `state` embeds the entire transcript and a rolling 200 request IDs. This gives stable resumes and keeps answer rubrics fixed for existing sessions. Every message rewrites state and returns the full transcript; the 1,000-event cap is checked before the action can append multiple events. Persistent `review_attempts` protects accepted answer deduplication, but non-answer request IDs eventually roll out of history. **Recommendation:** before larger cohorts or indefinite history, define transcript pagination/archive, request-id retention and a precise event limit. Do not split it prematurely for the four-lesson demo. Evidence: `app/services/review.py:24,94–161,552–583`, `app/models/review.py:30–43`, `docs/review-companion.md`.

### P2 — Documentation currently overstates the implementation

`app/main.py` advertises profile, conversation, lesson planning and live-session tags, but mounts only auth, users and review routers. `README.md` says every student-data table has `school_id`; `refresh_tokens` instead reaches a school through `users`. It also says all tests run without a database, whereas eight tests are opt-in PostgreSQL tests. `docs/rafiqi-engineering-plan-simplified.md` still describes the superseded A/B/C scope; `.claude/STATUS.md` has both current D4/D6 notes and stale `54/54` status. **Recommendation:** make the README a truthful operational entry point, mark superseded plans prominently, generate OpenAPI from current mounted routes, and maintain a ticket matrix with separate `designed`, `schema`, `API`, `integrated`, and `verified` states. Evidence: cited files and the current 25-operation OpenAPI.

## Alignment with boards and stories

| Scope / story | Backend assessment | Board/document implication |
|---|---|---|
| Board 41 persistent mock review | **Substantially implemented.** One permanent school/student/lesson session; bilingual seeded catalog; answers, hints, help, resume, attempts and completion. | Board 41 explicitly approves a mock and a single conversation. Current `review-companion.md` is a narrower and more current contract than Epic D's original stage/repeat-session language. |
| D1 session model | **Partial against broad Epic D.** Resumable, but DB uniqueness forbids multiple distinguishable runs for the same student/lesson. | This is correct for Board 41 and conflicts with `docs/artifact.md:129`; keep a documented scope override, and design repeats only if product approves a later version. |
| D2 state machine | **Mock slice only.** The service has bounded question transitions and prevents skipping; the original explicit Check-In/Deepen stage model is absent. | Board 41 explicitly removes those stages. Do not mark full D2 acceptance complete. |
| D3 assessment | **MVP implemented for curated lessons.** Attempts and stable taxonomy are persisted and checked. | New authored lessons/subjects need taxonomy and bilingual validation, or answers can be rejected. |
| D4 mastery | **Student concept projection implemented.** Source attempts remain immutable; thresholds and upsert are explicit. | No `ClassGroup` model or teacher/class aggregation, so broader D4 and E2 are incomplete. |
| D5 next step and hints | **Deterministic mock implemented.** Bounded hints, three attempts and sequential questions. | No adaptive AI selection or validated pedagogical model. |
| D6 completion | **Summary and mastery implemented; profile handoff absent.** | Backend `docs/review-companion.md` explicitly narrows the handoff to D4. Broader Epic D6 remains partial. |
| A1–A9 profile | **Schema scaffold only.** `student_profiles`, `profile_traits` and a conversation anchor exist; no mounted profile/conversation API, profile correction, provenance UI contract, teacher edits or governed retention. | Boards 34/35 approve frontend-only onboarding and explicitly exclude backend persistence. Do not treat demo onboarding as A2/A3 completion. |
| B1–B8 pre-class | **No matching backend domain/API.** Global review lessons are curated study content, not teacher-owned lesson preparation, warm-up submissions or misconception digests. | Boards 23–28 document local UI states, several design directions and approvals; they do not themselves authorize or verify backend persistence. |
| E1–E5 homework | **No matching backend domain/API.** | Revision 2 requires class grouping, evidence provenance, objective auto-marking and explicit teacher approval before sending work. |
| C1–C8 during class | **Absent as intended.** | Revision 2 defers realtime to v2; do not count this as a v1 defect. |

## What is working well

- One modular FastAPI application is appropriate to the current team and domain size. SQLAlchemy async sessions, Alembic migrations and Pydantic response models are a usable base.
- The review subsystem uses row locking for message updates, expected versions, request IDs and uniqueness constraints. It stores the lesson snapshot so later catalog edits do not silently reinterpret prior answers.
- The global catalog is separate from student records; seeded bilingual content is validated for concept references and assessment taxonomy. Public question projection excludes answer keys and unrevealed hints.
- Mastery is a recomputable projection over immutable attempt rows. It remains separate from narrative learner traits, matching the product's distinction between *how a student learns* and *what they understand*.
- The four-lesson review mock and its limits are described candidly in `docs/review-companion.md`. The local unit suite passes.

## Recommended delivery sequence

1. **Protect current surfaces:** fix token rotation, decide deactivation latency, verify uploaded media, and add production configuration checks. Add PostgreSQL-backed CI and contract tests.
2. **Resolve the A8 decisions:** consent, retention, deletion/export, transfer, access auditing, profile correction/provenance, and whether student avatars are public. Record the decision before building real profile inference or broader performance-data uses.
3. **Make the scope ledger honest:** publish the Board 41 override for D1/D2/D6, remove misleading OpenAPI claims, reconcile the frontend auth contract, and keep a stable story-to-API status matrix.
4. **Build the v1 spine in dependency order:** governed profile/conversation/correction; class/group and teacher-owned prep; warm-up with coverage-aware insights; teacher-facing profile/mastery digest; homework evidence lineage, approval, distribution and feedback. Preserve the explicit v2 deferral of realtime.

## Verification and limits

- Backend `HEAD` matched fetched `origin/main` at `ad0717c` during this review.
- FastAPI generated **25 operations**; only auth, user and review routers are mounted.
- `.venv/Scripts/python.exe -m pytest -q -ra`: **69 passed, 8 skipped** in 2.27 seconds. No dedicated disposable PostgreSQL test database was supplied, so concurrent refresh, data migrations and full API persistence were not independently exercised here.
- Docker is installed, but no live application database was inspected or changed. The frontend working tree contains unresolved merge conflicts; frontend contract observations were limited to the visible source and documentation.
- This review does not claim legal compliance or a measured security exploit. The severity labels reflect impact if used with real school/student data.

