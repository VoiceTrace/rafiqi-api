# Rafiqi — Build Status

## Current State

**A1 complete.** Data models, migration, schemas, and tests all green. Ready for A2.

## Session History

### Session 1 (2026-09-12)
- Read CLAUDE.md and ticket plan
- Confirmed `rafiqi-api` is an empty git repo — no code scaffolded yet
- Confirmed `rafiki-frontend` exists but is not to be touched until a backend piece is stable
- STATUS.md created and moved to `.claude/STATUS.md` by user
- Three skills scaffolded and organized: `fastapi-conventions`, `db-migrations`, `testing`
- Stack confirmed (see Tech Stack below) — unblocked, ready for A1

## Tech Stack

**Confirmed:**
- **Language/framework**: Python + FastAPI (async end to end)
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy (async)
- **Migrations**: Alembic
- **Testing**: pytest + pytest-asyncio + httpx.AsyncClient
- **Multi-tenancy**: row-level `school_id` scoping on all student/teacher/school tables
- **LLM gateway**: Claude (Haiku-class for high-volume cheap tier, stronger model for synthesis) — per CLAUDE.md model strategy

**Still open:**
- Auth approach (JWT custom vs. Supabase Auth vs. other)
- Hosting/infra + KSA data residency requirement (PDPL)
- Real-time layer for C2 (WebSocket vs. SSE vs. third-party pub-sub)

## Completed Tickets

### A1 — Profile data model (2026-09-12)
**What was built:**
- Full project scaffold: `app/`, `alembic/`, `tests/`, `requirements.txt`, `.env.example`
- SQLAlchemy models: `School`, `User`, `StudentProfile`, `ProfileTrait`, `Conversation`
- Migration: `alembic/versions/ef81a87bd4aa_a1_initial_schema.py` (hand-written — no local DB)
- Pydantic schemas: `app/schemas/profile.py` — `ProfileTraitOut`, `StudentProfileOut`, `TraitKey` controlled vocabulary
- 14 passing tests covering model columns, indexes, confidence threshold, enums
- `app/core/`: `config.py`, `database.py`, `errors.py`

**Key decisions made:**
- `score` (float 0.0–1.0): agent-facing, how confident LLM is about this trait
- `confidence` ("confident" | "still_forming"): user-facing label, derived from score (threshold = 0.7)
- `trait_key`: plain string in DB, controlled vocabulary enforced at app layer via `TraitKey` StrEnum — no migration needed when adding new trait types
- `category`: "preferences" | "goals" — matches the two UI card sections in the frontend
- `source_conversation_id` on `ProfileTrait`: FK to conversations, wired now so A4 doesn't require a migration later

## Next Ticket

**A2** — Cave chat
- Student talks with Rafiqi in "Rafiqi's Cave" to build the profile conversationally
- Needs: auth dependency (first route that requires it), LLM integration (Claude Haiku), conversation session management
- **Stop before starting**: auth approach still undecided — need to confirm before wiring the first protected route

## Build Order (from CLAUDE.md)

1. Foundations: A1, A2, B1, C1, C2
2. Profile loop: A3 → A6 → A7
3. Pre-class loop: B2/B3 → B5 → B6/B7
4. Live-class loop: C3 → C4 → C5 → C6
5. Don't leave for later: A5, A8
6. Nice-to-haves: A9, B4, B8, C7, C8

## Open Questions / Decisions to Track

- [ ] Auth approach: JWT custom vs. Supabase Auth vs. other?
- [ ] PDPL/A8: what trait fields are allowed to be stored? Must resolve before A3 storage depth is built
- [ ] Arabic LLM quality: needs explicit testing, not assumed — when to test?
- [ ] Real-time layer for C2: WebSocket vs. SSE vs. third-party pub-sub (Ably, Pusher, etc.)?
- [ ] KSA hosting: is infra required to be in-region for PDPL compliance?

## Decisions Made

- **Multi-tenancy**: row-level `school_id` FK on all student/teacher/school tables (confirmed via db-migrations skill)
- **Stack**: Python/FastAPI + PostgreSQL + SQLAlchemy + Alembic + pytest-asyncio (confirmed via skills)
