# Rafiqi — Project Context

This file gives Claude Code full context on Rafiqi and the EntraI venture it belongs to. Read this before working on any part of the codebase.

**Source of truth**: `docs/artifact.md` — the reviewed and revised MVP engineering plan (Revision 2, Younis, 2026-09-15). This supersedes the original `docs/rafiqi-engineering-plan-simplified.md`. Read `docs/artifact.md` before any ticket work.

**Companion file**: `docs/Rafiqi-big-plan.md` holds the long-term vision. It is NOT auto-loaded and is not current build scope — only read it if explicitly asked to plan toward it.


## The product: Rafiqi (a.k.a. "Rafiqi" in the mockup and tickets)

Education app for schools, teachers, and students. First priority build to  catch the dead line.

**Market**: MENA first, starting with **Saudi Arabia (KSA)**.
- Content/curriculum must align to the Saudi MOE curriculum, not Egyptian.
- **PDPL (Saudi Personal Data Protection Law)** applies — fully enforced since Sept 2024, regulator is SDAIA. A DPO is mandatory for orgs processing data of children/vulnerable individuals, which this product does by definition. Cross-border data transfer requires documented safeguards if infra isn't hosted in KSA. Get compliance/legal input before the first real school rollout.
- This maps directly onto ticket A8 (privacy review) — see below. Do it early, not as a launch afterthought.


## Tech Stack (confirmed 2026-09-12)

- **Language/framework**: Python + FastAPI (async end to end — all routes `async def`)
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy (async driver)
- **Migrations**: Alembic — see `.claude/skills/db-migrations/SKILL.md`
- **Testing**: pytest + pytest-asyncio + httpx.AsyncClient — see `.claude/skills/testing/SKILL.md`
- **API conventions**: see `.claude/skills/fastapi-conventions/SKILL.md`
- **Architecture enforcement**: see `.claude/skills/python-architecture/SKILL.md` — load this when reviewing agent-generated code; catches DB-in-controller, HTTPException-in-service, missing response_model, bare error strings
- **Multi-tenancy**: row-level `school_id` FK on every student/teacher/school table — hard rule, not optional
- **LLM gateway**: OpenRouter (changed 2026-09-27, was "Claude direct") — OpenAI-compatible API, model chosen by config string (`CAVE_CHAT_MODEL`, `SAFETY_CLASSIFIER_MODEL`, `PROFILE_EXTRACTION_MODEL` in `app/core/config.py`) so the cheap-tier model (currently Kimi K2) can be swapped without a code change. Router-pattern intent unchanged: cheap/fast tier for high-volume per-turn calls (A2 chat, B2 draft, B5 prompts), a stronger model reserved for lower-volume synthesis (B6 misconception summary) when that ends up needing real synthesis.
- **Auth**: custom JWT — access token (30 min, python-jose + bcrypt) + rotating opaque refresh token (30 days, hashed at rest, revocable via `POST /auth/logout`), payload carries user_id + school_id + role. Two roles today: `teacher`, `student`, enforced via `require_teacher`/`require_student` deps in `app/api/deps.py`. Known open item: a still-valid access token isn't revoked immediately on user deactivation (bounded to the 30 min access-token lifetime, since refresh already re-checks `is_active`) — see `.claude/STATUS.md` Open Decisions if closing this fully becomes a priority.
- **Hosting/infra**: not yet decided — PDPL KSA data residency requirement must be resolved before first school rollout
- **Real-time**: not required for v1 — Epic C is deferred

## Notes for Claude Code

- This file should be updated as decisions get made — treat it as living project memory, not a one-time brief.
- When ticket-plan details and earlier prose descriptions conflict anywhere in this file, the ticket-plan wording wins.
- Always read `.claude/STATUS.md` at the start of a session before doing anything else — it records exactly where work stopped.
- Apply the relevant skill(s) from `.claude/skills/` for every ticket: `fastapi-conventions` when adding routes/schemas/services, `db-migrations` when touching models/tables, `testing` before marking any ticket done, `python-architecture` when reviewing any agent-generated code.
- **Agent code (Codex)**: `AGENTS.md` at the repo root is the authoritative instruction file for Codex. If Codex-generated code shows DB queries in route files, `HTTPException` in service files, or missing `response_model`, run the `python-architecture` skill and flag it before merging.