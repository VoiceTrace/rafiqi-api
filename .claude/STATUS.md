# Rafiqi — Build Status

## ⚠ Scope change (2026-09-15)

`docs/artifact.md` (Revision 2, Younis) is now the source of truth. Read it before any ticket work.

**Key changes vs the original plan:**
- **Epic C (during-class) deferred to v2** — no realtime infrastructure in v1
- **Epic D (Study Sessions) added** — 6 tickets, replaces C as source of behavioural/performance data
- **Epic E (Homework Generation) added** — 5 tickets, differentiated per student from mastery data
- **`MasteryRecord` (D4) is now a blocker** for Epic E — concept-level mastery must exist before targeted homework can be generated
- **A8 must be resolved before A1 is finalised** — A8 determines schema, retention rules, and compliance surface

---

## Current State

**A1 + Auth (incl. refresh/logout) complete. DB running.** 54/54 tests green.

> **Before starting A2:** A8 decisions must be made (see Open Decisions below). A8 now covers performance data (D3/D4) and parent-visible output (E3) in addition to the original profile data scope.

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
- `alembic upgrade head` verified clean against a throwaway Postgres container (the
  project's own `docker-compose` `rafiqi-db` port conflicted with a system-wide
  `postgresql@12` service already bound to 5432 in this environment — worth the team
  knowing about if it hits others), `alembic check` confirms no model/migration drift.
- Full suite: 54/54 passing.

---

## Tech Stack

**Confirmed:**
- **Language/framework**: Python + FastAPI (async end to end)
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy (async)
- **Migrations**: Alembic
- **Testing**: pytest + pytest-asyncio + httpx.AsyncClient
- **Multi-tenancy**: row-level `school_id` scoping on all student/teacher/school tables
- **LLM gateway**: Claude (Haiku-class for high-volume cheap tier, stronger model for synthesis)
- **Auth**: custom JWT access token (30 min, python-jose + bcrypt) + rotating opaque refresh token (30 days, DB-backed, revocable via logout), payload carries user_id + school_id + role
- **Docker DB**: postgres:16-alpine, container name `rafiqi-db`, port 5432

**Still open:**
- Hosting/infra + KSA data residency (PDPL)
- Realtime layer — not required for v1 (Epic C deferred)

---

## Completed Tickets

### A1 — Profile data model (2026-09-12)
**What was built:**
- Full project scaffold: `app/`, `alembic/`, `tests/`, `requirements.txt`, `.env.example`
- SQLAlchemy models: `School`, `User`, `StudentProfile`, `ProfileTrait`, `Conversation`
- Migration: `alembic/versions/ef81a87bd4aa_a1_initial_schema.py`
- Pydantic schemas: `app/schemas/profile.py` — `ProfileTraitOut`, `StudentProfileOut`, `TraitKey`
- 14 passing tests covering model columns, indexes, confidence threshold, enums
- `app/core/`: `config.py`, `database.py`, `errors.py`

**Key decisions made:**
- `score` (float 0.0–1.0): agent-facing confidence
- `confidence` ("confident" | "still_forming"): user-facing label, threshold = 0.7
- `trait_key`: plain string in DB, controlled vocabulary via `TraitKey` StrEnum
- `category`: "preferences" | "goals"
- `source_conversation_id` on `ProfileTrait`: FK to conversations, wired for A4

**⚠ Revision 2 note:** A1 schema will need extension to reference `MasteryRecord` (D4). Do not treat A1 as fully closed until D4's model shape is decided (see Open Decisions).

---

## Build Order (Revision 2)

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
| **A8: who consents** (guardian, school, or both) | A1 finalised, A3 | Written data-handling note required, not just a review |
| **A8: retention period + deletion rights** | A1 finalised | Post-retention handling and guardian deletion rights |
| **A8: performance data scope** | D3, D4 | Attempts/errors are more sensitive than behavioural reads |
| **A8: parent-visible output policy** | E3 | Epic E sends output to the home — widens compliance surface |
| **A3: promotion rule** (forming → confident) | A3 | Number of observations? Consistency across subjects? Elapsed time? |
| **A6: disclosure rule** | A6 | Narrative reads only — no numeric scores, no comparative framing |
| **D4: mastery model shape** | D3, D4, E1–E5 | What is a `MasteryRecord`? Attempts, outcomes, dominant error pattern per concept |
| **N6: school validation call** | E (whole epic) | Confirm device access in class and homework policy by year group before Epic E is built |
| **B5: participation mechanics** | B5, B6 | Reminder timing, definition of completion, behaviour at low participation |
| **B6: coverage threshold** | B6 | Below threshold the card states low coverage, not a class-level claim |
| **Auth: immediate access-token revocation** | hardening, not a ticket blocker | Access tokens (30 min) are still trusted purely from their signature — a deactivated user keeps API access for up to 30 min. Closing fully needs a per-request active-user check (DB hit or cache) traded against latency; refresh already re-checks `is_active`, which caps real exposure at the access-token lifetime. Revisit if PDPL/A8 review calls for stricter immediacy |

---

## Decisions Made

- **Multi-tenancy**: row-level `school_id` FK on all student/teacher/school tables
- **Stack**: Python/FastAPI + PostgreSQL + SQLAlchemy + Alembic + pytest-asyncio
- **Auth**: custom JWT access token (30 min) + rotating refresh token (30 days), payload carries user_id + school_id + role
- **Docker DB**: postgres:16-alpine, port 5432
- **Epic C**: deferred to v2 — no realtime infrastructure in v1
- **E3 format constraint**: self-checking formats only (single correct answer, MCQ, spot-the-error) — no human marking required
- **Visible differentiation (E3)**: same item count and presentation across class; variation in scaffolding and concept focus only — no student-visible difficulty label
- **Trust principle (B3, A5, A9, E4)**: Rafiqi proposes, the human decides — applies everywhere
