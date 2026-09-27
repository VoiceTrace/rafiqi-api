# Rafiqi — Build Status

## ⚠ Scope change (2026-09-15)

`docs/artifact.md` (Revision 2, Younis) is the source of truth. Read it before any ticket work.
(Note: `.claude/CLAUDE.md` was trimmed on 2026-09-27 to stop duplicating ticket-level detail
that lives in `docs/artifact.md` — read `docs/artifact.md` directly for epic/ticket definitions,
hard rules, and system design, not CLAUDE.md.)

**Key changes vs the original plan:**
- **Epic C (during-class) deferred to v2** — no realtime infrastructure in v1
- **Epic D (Study Sessions) added** — 6 tickets, replaces C as source of behavioural/performance data
- **Epic E (Homework Generation) added** — 5 tickets, differentiated per student from mastery data
- **`MasteryRecord` (D4) MVP is implemented** — concept-level records now exist; ClassGroup aggregation is still required before Epic E
- **A8 must be resolved before A1 is finalised** — A8 determines schema, retention rules, and compliance surface (still open — see below)

---

## Current State

**A1 + Auth (incl. refresh/logout) + A2/A3 (Cave chat + extraction) + A5/A6 (correction + student view) + safety layer complete. DB running.** 77/77 tests green.

> **A8 is still unresolved.** A2/A3 were built on 2026-09-27 with A8 explicitly *not* resolved first — the user made an informed call to skip the A8 write-up and build anyway rather than block on it. This is a real, acknowledged compliance gap, not an oversight: no consent/retention/deletion-rights decision has been documented, and A3 stores whatever the extraction prompt produces with no hard ceiling on storage depth. Get compliance/legal input before any real school rollout, per CLAUDE.md/artifact.md.

---

## Session History

### Session 1 (2026-09-12)
- Read CLAUDE.md and ticket plan
- Confirmed `rafiqi-api` is an empty git repo — no code scaffolded yet
- Confirmed `rafiki-frontend` exists but is not to be touched until a backend piece is stable
- STATUS.md created and moved to `.claude/STATUS.md` by user
- Three skills scaffolded and organized: `fastapi-conventions`, `db-migrations`, `testing`
- Stack confirmed (see Tech Stack below) — unblocked, ready for A1

### Session 2 (2026-09-15)
- `docs/artifact.md` received and formatted — Revision 2 review by Younis
- CLAUDE.md updated: source of truth, scope, build order, system design, risks all revised
- STATUS.md updated to reflect new scope and open decisions
- Epic C fully deferred; Epics D and E added to plan

### Session 3 (2026-09-21) — JWT refresh + logout
- Found role-based auth (teacher/student, `require_teacher`/`require_student` deps) and JWT
  login already in place from a prior session's `A-USER` work — no new role system needed.
- Real gap found in the existing JWT flow: access tokens were trusted purely from their
  signature, with no DB check — a deactivated user's token stayed valid for the full 6h
  lifetime instead of losing access immediately.
- Added a `refresh_tokens` table (hashed opaque tokens, revocable, one row per issued
  refresh token) and `POST /auth/refresh` / `POST /auth/logout` routes.
- Shortened access tokens from 6h to `ACCESS_TOKEN_EXPIRE_MINUTES` (30 min) now that a
  refresh token covers the long-lived session — this shrinks (but doesn't close) the
  deactivation-lag window found above, since refresh itself now re-checks `is_active`.
  Immediate access-token revocation on deactivation is still open — see Open Decisions.
- Refresh tokens rotate on every use (old one revoked, new one issued) so replaying a
  stolen-then-already-used refresh token is rejected.
- `alembic upgrade head` verified clean, `alembic check` confirms no model/migration drift.
- Full suite: 54/54 passing.

### Session 4 (2026-09-27) — Rafiqi's Cave (A2/A3) + safety layer

- Built the Cave chat backend: `POST /conversations` (start, Rafiqi generates an
  opening line), `POST /conversations/{id}/messages` (send/receive), `POST
  /conversations/{id}/end` (ends + triggers A3 extraction), `GET
  /conversations/{id}` (resume), `GET /conversations/flags` (teacher-only
  safety log). New `ConversationMessage` model/table (migration `6d4c3dbc83c1`).
- **LLM gateway changed to OpenRouter** (was "Claude direct" in Tech Stack) —
  user's explicit choice, so the cheap-tier model (Kimi K2 by default) is a
  config string, not a code change. Plain `httpx` calls in `app/services/llm.py`,
  no new SDK dependency. New env vars: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`,
  `CAVE_CHAT_MODEL`, `SAFETY_CLASSIFIER_MODEL`, `PROFILE_EXTRACTION_MODEL`.
- **Safety layer**: every student message is classified (`app/services/safety.py`)
  for `self_harm` / `abuse` / `bullying` / `distress` / `cheating` before the
  chat model ever sees it. A flagged message gets a fixed, deterministic
  scripted reply (never model-generated) and is logged (`flagged`,
  `flag_category` on `ConversationMessage`) — readable via `GET
  /conversations/flags`. No notification/alerting beyond that log exists yet.
  Classifier **fails open** (unflagged) on any parse/gateway error — a known
  MVP limitation, not a hardened fail-closed gate.
- **A3 promotion rule resolved (v1)**: `new_score = existing_score * 0.7 + observed_score * 0.3`.
  Superseded in Session 5 — see below.
- **A8 explicitly not resolved before this work** — user's call, made knowingly.
- No conftest.py / real-DB test infra exists in this repo — all tests mock `AsyncSession`.
- Full suite: 70/70 passing.

### Session 5 (2026-09-27) — trait vocabulary expansion, A5 + A6, A3 v2, persona rewrite

- **Expanded the trait vocabulary**: `TraitCategory` only had `preferences`/`goals`, which
  didn't cover the mockup's full "How Rafiqi sees you" panel (How you learn, What drives you,
  How you feel, Study habits, Language & company, Your world). Added 4 categories —
  `wellbeing`, `study_habits`, `social`, `context` — and ~16 new `TraitKey` entries across
  them (`app/schemas/profile.py`, `app/models/profile.py`). No migration needed — `trait_key`/
  `category` are plain strings by design. Note: the mockup's "Where you are" card was
  deliberately **not** added here — per CLAUDE.md/artifact.md's data model split, concept-level
  academic state belongs to `MasteryRecord` (Epic D, not built), not the trait/profile system.
- **A6 built**: `GET /profiles/me` — narrative-only student view. Per the disclosure rule
  already proposed in `docs/artifact.md` §1 (A6, Blocker) — "narrative reads and
  teaching-relevant statements only — no numeric trait scores, no comparative framing" — the
  response schema (`StudentTraitCardOut`) has no `score` field at all, only the derived
  confidence label. Empty card list for a student who hasn't chatted yet (not an error).
- **A5 built alongside it** (per artifact.md's explicit "ship alongside A6, not after" rule):
  `POST /profiles/traits/{trait_id}/flag` — student flags a card with a reason, resolved
  synchronously in the same request (no job queue in this stack). One LLM call decides the
  revised description/tip/score; on any LLM failure it fails safe (conservatively resets
  toward "still_forming" rather than leaving the disputed trait looking untouched). Every flag
  is recorded in a new `profile_trait_corrections` table (migration `3a358f4ca337`) as an
  audit trail, kept even after resolution, in the spirit of A4's trust/debuggability goal.
- **A3 extraction redesigned (v2)** — supersedes Session 4's fixed 0.7/0.3 formula. The model
  is now shown the *current* profile state (existing traits + scores) in the extraction
  prompt and asked to propose a target score itself, reinforcing/contradicting/filling gaps —
  rather than the code blindly re-weighting a value the model never saw. Code now only clamps
  how far a single session can move an *existing* trait's score (±0.3 max), as a pure
  stability guard; a brand-new trait is created at whatever the model proposes, no clamp.
  `app/services/profile_extraction.py`.
- **Cave persona prompt rewritten** (`app/services/cave.py`) to make the real brief explicit
  to the model: build a picture across all 6 trait categories, but get there *indirectly*
  (scenarios, tangents, reacting like a person) rather than interviewing — and stay genuinely
  interesting/playful, not just "warm and curious" as a vibe.
- Not built: A7 (teacher roster), A9 (teacher hand-edit — note: artifact.md's review actually
  proposes *promoting* A9 to MVP as "the teacher-side mirror of A5", not requested this
  session), any notification when a trait gets flagged or a message gets safety-flagged.
- **`.claude/STATUS.md` was found completely empty at the start of this session** (not
  trimmed like CLAUDE.md — zero bytes). Restored from this session's own context since the
  project's workflow depends on it (`CLAUDE.md`: "Always read STATUS.md at the start of a
  session"). Flagged to the user directly — if the wipe was intentional, this restore should
  be reverted/redone in whatever format was actually wanted.
- Full suite: 77/77 passing.

---

## Tech Stack

**Confirmed:**
- **Language/framework**: Python + FastAPI (async end to end)
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy (async)
- **Migrations**: Alembic
- **Testing**: pytest + pytest-asyncio + httpx.AsyncClient (route-level httpx tests not yet
  used in practice — all current tests mock `AsyncSession`, see Session 4 note)
- **Multi-tenancy**: row-level `school_id` scoping on all student/teacher/school tables
- **LLM gateway**: OpenRouter (changed 2026-09-27, was Claude direct) — model chosen by
  config string, cheap tier currently Kimi K2
- **Auth**: custom JWT access token (30 min) + rotating refresh token (30 days, DB-backed,
  revocable via logout), payload carries user_id + school_id + role
- **Docker DB**: postgres:16-alpine, container name `rafiqi-db`. **Local note**: this
  machine's `docker-compose.yml` maps `5432:5432`, but a system-wide Postgres already
  occupies 5432 here — `.env` on this machine uses port `5433` instead (`docker run ... -p
  5433:5432 postgres:16-alpine`), matching neither `docker-compose.yml` nor `.env.example`.
  Worth reconciling `docker-compose.yml` if this trips up another machine.

**Still open:**
- Hosting/infra + KSA data residency (PDPL)
- Realtime layer — not required for v1 (Epic C deferred)

---

## Completed Tickets

### A1 — Profile data model (2026-09-12, extended 2026-09-27)
**What was built:**
- Full project scaffold: `app/`, `alembic/`, `tests/`, `requirements.txt`, `.env.example`
- SQLAlchemy models: `School`, `User`, `StudentProfile`, `ProfileTrait`, `Conversation`
- Migration: `alembic/versions/ef81a87bd4aa_a1_initial_schema.py`
- Pydantic schemas: `app/schemas/profile.py` — `ProfileTraitOut`, `StudentProfileOut`, `TraitKey`

**Key decisions made:**
- `score` (float 0.0–1.0): agent-facing confidence
- `confidence` ("confident" | "still_forming"): user-facing label, threshold = 0.7
- `trait_key`: plain string in DB, controlled vocabulary via `TraitKey` StrEnum
- `category`: originally "preferences" | "goals"; **extended 2026-09-27** to also include
  `wellbeing`, `study_habits`, `social`, `context` (see Session 5)
- `source_conversation_id` on `ProfileTrait`: FK to conversations, wired for A4

**Revision 2 note:** The D4 MVP `MasteryRecord` model now exists. A future A1/Profile integration should reference it without merging mastery into narrative profile traits.

### A2/A3 — Cave chat + profile extraction + safety layer (2026-09-27, extraction revised same day)
**What was built:**
- `app/models/message.py`: `ConversationMessage` (+ migration `6d4c3dbc83c1`)
- `app/services/llm.py`: OpenRouter gateway client (plain `httpx`)
- `app/services/safety.py`: per-message classifier + deterministic scripted replies
- `app/services/cave.py`: chat orchestration (start/post/end/get/list_flags), persona prompt
- `app/services/profile_extraction.py`: A3 model-informed extraction + clamped merge (v2)
- `app/api/routes/cave.py`: 5 routes under `/conversations`

**Key decisions made:** LLM gateway → OpenRouter; A3 promotion rule (v2) → model proposes a
target score having seen the current profile, code clamps movement to ±0.3/session for
existing traits; safety classifier fails open; flagged turns excluded from extraction
transcript. **A8 knowingly not resolved first.**

### A5/A6 — Student correction + profile view (2026-09-27)
**What was built:**
- `app/models/profile.py`: `ProfileTraitCorrection` (+ migration `3a358f4ca337`)
- `app/services/profile.py`: `get_own_profile_cards`, `flag_trait`
- `app/api/routes/profiles.py`: `GET /profiles/me`, `POST /profiles/traits/{id}/flag`
- `app/schemas/profile.py`: `StudentTraitCardOut` (no `score` field — A6 disclosure rule),
  `StudentProfileViewOut`, `TraitFlagIn`, `TraitFlagOut`

**Key decisions made:** A6 disclosure rule adopted as literally proposed in `docs/artifact.md`
§1 (narrative + teaching-relevant statements only, no numeric scores, no comparative framing).
A5 resolved synchronously (no pending/disputed state persisted) rather than queued — matches
the rest of this stack's sync-only architecture. Correction record kept permanently as an
audit trail even after resolution.

---

## Build Order (Revision 2 — see docs/artifact.md §7 for the authoritative version)

```
0. Decisions first (no code)   A8 answers · A3 promotion rule · A6 disclosure rule
                               · D4 mastery model shape · N6 school validation call
1. Foundations                 A1 · A2 · B1
2. Profile loop + trust        A3 → A6 + A5 → A7 + A9
3. Study loop                  D1 · D2 → D3 → D4 → D5 → D6
4. Pre-class loop              B2/B3 → B5 + N4 → B6/B7
5. The link                    N1  (profile digest into prep)
6. Homework loop               E1 → E2 → E3 + E4 → E5
7. Polish                      B4 · B8
–  Live loop (v2 only)         C1 · C2 → C3 → C4 → C5 → C6 → C8
```

---

## Open Decisions — must resolve before the relevant ticket is built

| Decision | Blocks | Notes |
|----------|--------|-------|
| **A8: who consents** (guardian, school, or both) | A1 finalised, A3 | Written data-handling note required, not just a review. **Still open — knowingly skipped, see Sessions 4/5.** |
| **A8: retention period + deletion rights** | A1 finalised | Post-retention handling and guardian deletion rights. Raw Cave transcripts are currently retained indefinitely with no purge job. |
| **A8: performance data scope** | D3, D4 | Attempts/errors are more sensitive than behavioural reads |
| **A8: parent-visible output policy** | E3 | Epic E sends output to the home — widens compliance surface |
| ~~A3: promotion rule~~ | ~~A3~~ | **Resolved 2026-09-27, revised same day (v2)**: model proposes a target score seeing current state, code clamps to ±0.3/session — see Session 5 |
| ~~A6: disclosure rule~~ | ~~A6~~ | **Resolved 2026-09-27**: adopted artifact.md's proposed rule verbatim — narrative + teaching-relevant only, no scores, no comparison |
| **N6: school validation call** | E (whole epic) | Confirm device access in class and homework policy by year group before Epic E is built |
| **B5: participation mechanics** | B5, B6 | Reminder timing, definition of completion, behaviour at low participation |
| **B6: coverage threshold** | B6 | Below threshold the card states low coverage, not a class-level claim |
| **Auth: immediate access-token revocation** | hardening, not a ticket blocker | Access tokens (30 min) are still trusted purely from their signature — a deactivated user keeps API access for up to 30 min. Refresh already re-checks `is_active`, capping real exposure at the access-token lifetime. |
| **A9: promote to MVP?** | A9 | `docs/artifact.md` explicitly recommends promoting A9 ("teacher-side mirror of A5") from nice-to-have to MVP. Not built yet — not requested as of Session 5. |

---

## Decisions Made

- **Multi-tenancy**: row-level `school_id` FK on all student/teacher/school tables
- **Stack**: Python/FastAPI + PostgreSQL + SQLAlchemy + Alembic + pytest-asyncio
- **Auth**: custom JWT access token (30 min) + rotating refresh token (30 days), payload carries user_id + school_id + role
- **Docker DB**: postgres:16-alpine — see local port note under Tech Stack above
- **Epic C**: deferred to v2 — no realtime infrastructure in v1
- **E3 format constraint**: self-checking formats only (single correct answer, MCQ, spot-the-error) — no human marking required
- **Visible differentiation (E3)**: same item count and presentation across class; variation in scaffolding and concept focus only — no student-visible difficulty label
- **Trust principle (B3, A5, A9, E4)**: Rafiqi proposes, the human decides — applies everywhere
- **D4 MVP mastery policy**: latest attempt per lesson/question is current evidence; average correctness maps to `needs_support` (<0.5), `developing` (0.5–<0.8), or `secure` (>=0.8); retries correct the projection while preserving attempts; confidence and evidence windows are deferred
- **D6 MVP completion policy**: the final transition atomically refreshes D4 and creates one immutable, bilingual-rendered session summary; replay/reload returns the same summary; profile and homework automation are deferred
