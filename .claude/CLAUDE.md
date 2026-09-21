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

## MVP scope (Revision 2 — per `docs/artifact.md`)

**In scope**: **Epic A** (Student Profile), **Epic B** (Pre-Class), **Epic D** (Study Sessions), **Epic E** (Homework Generation).
**Explicitly deferred to v2**: **Epic C** (During-Class / live engagement). Do not build any realtime infrastructure.
**Out of scope**: human marking, open-response homework, group/peer study, anything realtime.

The product spine is: **Study → Profile → Prep + Homework → Study** — a closed loop that runs entirely outside class hours.

### Epic A — Student Profile

- **A1 (Foundation)** — profile data model: trait scores, freeform notes, teaching tips, and a confidence level per trait/field. Everything else in this epic depends on it.
- **A2** — Cave chat: student talks with Rafiqi in "Rafiqi's Cave" to build the profile conversationally, instead of filling out a form. General get-to-know-you, not tied to a specific lesson.
- **A3** — profile updates automatically from that chat, no manual entry. Each field is labeled "confident" or "still forming."
- **A4** — teacher can see which conversation a given trait came from, for trust/debuggability when a trait looks off.
- **A5** — student can flag a profile card as wrong and explain why ("not quite me?" correction).
- **A6** — student-facing live view of their own profile as it updates, so they can trust and correct it early.
- **A7** — teacher roster view showing each student's profile card. Students who haven't chatted yet must show clearly as "new" — never blank or broken.
- **A8 (Foundation, do early)** — data privacy review: school/parents need clarity on how a minor's personal and behavioral data is stored and used. This directly constrains how much detail A3 is allowed to save — resolve before building out A3's storage depth, not after.
- **A9 (nice-to-have)** — teacher can hand-edit a profile field directly.

### Epic B — Pre-Class

- **B1 (Foundation)** — lesson prep data model: objectives, flow, check-questions, materials.
- **B2** — teacher clicks "generate," gets an AI-drafted lesson prep (objectives, flow, check-questions) instead of starting blank.
- **B3** — teacher can edit, reorder, or delete anything generated.
- **B4 (nice-to-have)** — attach files from a materials library to a lesson.
- **B5** — student warm-up ("Prime"): a short **prediction game** before class tied to the day's topic — student predicts/picks an outcome for a scenario, plus one optional free-text "why do you think that?" field. **Decided (see docs/Rafiqi-big-plan.md for the fuller version)**: MVP builds the structured prediction format, not open multi-turn Socratic dialogue. No LLM needed in the core interaction loop; the optional free-text field is the only place generation/parsing touches this ticket. Aggregating for B6 is a tally over predicted outcomes, not taxonomy classification.
- **B6** — teacher sees the class's most common wrong guesses from B5 warm-ups before teaching, so they can plan to address them directly. This is the "misconception surfacing" feature — simpler than a full per-student diagnostic digest; it's an aggregated wrong-guess view, not a taxonomy-classified report (a formal misconception taxonomy can still inform how guesses are grouped/labeled, but the ticket doesn't require full taxonomy-based classification for MVP).
- **B7** — student can flag a question for the teacher ahead of time while chatting with Rafiqi, so it isn't lost before class.
- **B8 (nice-to-have)** — generate a slide presentation from finished prep.

### Epic C — During Class (new scope — real-time system, not previously designed for)

- **C1** — teacher starts a live session, students join — one shared session/"room."
- **C2 (Foundation, build early — everything else in this epic depends on it)** — the live connection layer: real-time sync of engagement, questions, and highlights between teacher and every student in the session. This requires a **WebSocket or equivalent pub-sub real-time layer** — this is new infrastructure not covered by the original system design (which only covered the async orchestrator → digest → dashboard flow).
- **C3** — teacher sees live who's note-taking, asking questions, or checked out.
- **C4** — student questions grouped by topic and ranked by how many students asked; teacher can tap a group to see who asked and how they phrased it.
- **C5** — teacher can push a "highlight this" that appears live on every student's screen instantly.
- **C6** — students can jot notes/questions during class; visible to the teacher for follow-up.
- **C7 (nice-to-have)** — Rafiqi notices if a student's own notes already answer a question they raised, and tells them.
- **C8 (Foundation)** — when a session ends, freeze/lock the engagement and question data so after-class summaries and profile updates can consume it without it changing underneath them.

### Build order (Revision 2 — from `docs/artifact.md` §7)

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

**Hard rules from the review:**
- A8 must be resolved before A1 is finalised — it determines the schema.
- A5 ships alongside A6, never after.
- D (study loop) comes before E (homework) — E consumes what D produces.
- Trust mechanisms (A5, A9, E4) ship with the features they protect.

## System design

**Async flow (v1):** Student app → Conversation orchestrator → (LLM gateway + Student profile store + MasteryRecord store) → downstream consumers (A3 profile update, D4 mastery update, B6/E2 class aggregation) → Teacher-facing view.

No realtime layer in v1. Epic C is deferred; 

**New in Revision 2:** The data model has two distinct halves:
- **Who the student is** — traits, narrative reads (`StudentProfile`, `ProfileTrait`)
- **What the student understands** — concept-level mastery (`MasteryRecord`, `Attempt`) — added by D3/D4

Both are queryable per student and aggregatable per `ClassGroup`. The LLM is stateless per call — context engineering from these two stores drives personalisation.

### Conversation orchestrator (still applicable to A2/A3 and B5)
Per turn: assembles context (student's existing profile state for A2/A3, or today's lesson topic for B5) → calls LLM gateway → for A2/A3, extracts/updates trait data with a confidence label (per A3); for B5, is likely a simpler prediction-question flow rather than the multi-turn Socratic loop originally assumed — confirm scope before building the guardrail-heavy version.

### Model strategy
Router pattern, not one model for everything:
- Cheap/fast tier (Haiku/GPT-4o-mini/Gemini-Flash class) for per-turn chat (A2 Cave chat, B2 lesson-prep generation drafts, B5 prediction prompts) — high volume, low stakes per call.
- Stronger model reserved for anything higher-stakes and lower-volume (e.g. B6 misconception aggregation/summary, if it ends up needing real synthesis rather than a simple tally).
- Rough scale: 3 pilot schools x 300 students → verify current pricing before budgeting, this space moves fast.

### Personalization mechanism
The LLM is stateless per call — personalization comes from context engineering, not fine-tuning per student. The A1 profile data model (traits, notes, tips, confidence) is the source of truth injected into prompts, not something the model "remembers" on its own.

### Data layer
Relational store for school/teacher/student/roles, multi-tenant isolated per school (non-negotiable given PDPL + multiple client schools). A1 (profile) and B1 (lesson prep) are the two foundational data models everything else depends on — build these first per the suggested order above.

## Known open risks / challenges to keep front of mind

**Technical**: curriculum content-ops lift (KSA-aligned), Arabic dialogue quality (generally weaker than English — needs explicit testing), multi-tenant data isolation, cost control at scale, mobile/tablet UX (small-screen conversational UI, voice input for younger students, shared-device session switching). Realtime infrastructure risk is removed for v1.

**Non-technical**: school procurement cycles are slow (paid trial ≠ guaranteed rollout), teacher adoption/trust (must feel like help, not assessment), homework policy varies by school and year group (X6 — validate before Epic E), parent/regulator trust re: AI talking to children and sending output to the home (widened compliance surface per A8 Revised), renewal depends on demonstrated outcomes.

**AI-specific**: A2/A3 profile extraction accuracy and scope (A8 constrains what can be stored), PDPL/minors'-data compliance (now covers performance data and parent-visible output), A3 output stability (same transcript → same updates), D3 error taxonomy design, hallucination risk on academic content (B2 lesson prep, E3 homework generation), Arabic vs English quality gap, safety guardrails for minors.

## Tech Stack (confirmed 2026-09-12)

- **Language/framework**: Python + FastAPI (async end to end — all routes `async def`)
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy (async driver)
- **Migrations**: Alembic — see `.claude/skills/db-migrations/SKILL.md`
- **Testing**: pytest + pytest-asyncio + httpx.AsyncClient — see `.claude/skills/testing/SKILL.md`
- **API conventions**: see `.claude/skills/fastapi-conventions/SKILL.md`
- **Multi-tenancy**: row-level `school_id` FK on every student/teacher/school table — hard rule, not optional
- **LLM**: Claude (Haiku-class for high-volume cheap tier: A2 chat, B2 draft, B5 prompts; stronger model for lower-volume synthesis: B6 misconception summary)
- **Auth**: custom JWT — access token (30 min, python-jose + bcrypt) + rotating opaque refresh token (30 days, hashed at rest, revocable via `POST /auth/logout`), payload carries user_id + school_id + role. Two roles today: `teacher`, `student`, enforced via `require_teacher`/`require_student` deps in `app/api/deps.py`. Known open item: a still-valid access token isn't revoked immediately on user deactivation (bounded to the 30 min access-token lifetime, since refresh already re-checks `is_active`) — see `.claude/STATUS.md` Open Decisions if closing this fully becomes a priority.
- **Hosting/infra**: not yet decided — PDPL KSA data residency requirement must be resolved before first school rollout
- **Real-time**: not required for v1 — Epic C is deferred

## Notes for Claude Code

- This file should be updated as decisions get made — treat it as living project memory, not a one-time brief.
- When ticket-plan details and earlier prose descriptions conflict anywhere in this file, the ticket-plan wording wins.
- Always read `.claude/STATUS.md` at the start of a session before doing anything else — it records exactly where work stopped.
- Apply the relevant skill(s) from `.claude/skills/` for every ticket: `fastapi-conventions` when adding routes/schemas/services, `db-migrations` when touching models/tables, `testing` before marking any ticket done.