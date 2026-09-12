# Rafiqi — Project Context

This file gives Claude Code full context on Rafiqi and the EntraI venture it belongs to. Read this before working on any part of the codebase.

**Source of truth**: where the engineering ticket plan (`docs/rafiqi-engineering-plan-simplified.md`) 

**Companion file**: `docs/Rafiqi-big-plan.md` holds the long-term/full-complexity vision (multi-turn Socratic dialogue, misconception taxonomy, homework personalization, deferred mockup screens, etc.). It is NOT auto-loaded by Claude Code and is not current build scope — only read it if explicitly asked to plan toward it. This file (the MVP ticket plan) is what to build against by default.


## The product: Rafiqi (a.k.a. "Rafiqi" in the mockup and tickets)

Education app for schools, teachers, and students. First priority build to  catch the dead line.

**Market**: MENA first, starting with **Saudi Arabia (KSA)**.
- Content/curriculum must align to the Saudi MOE curriculum, not Egyptian.
- **PDPL (Saudi Personal Data Protection Law)** applies — fully enforced since Sept 2024, regulator is SDAIA. A DPO is mandatory for orgs processing data of children/vulnerable individuals, which this product does by definition. Cross-border data transfer requires documented safeguards if infra isn't hosted in KSA. Get compliance/legal input before the first real school rollout.
- This maps directly onto ticket A8 (privacy review) — see below. Do it early, not as a launch afterthought.

## MVP scope (current — per engineering ticket plan)

**In scope**, for both teacher and student: **Student Profile, Pre-Class, During-Class.**
**Explicitly out of scope for now**: everything else shown in the original mockup — Homework, Study Cave (beyond what Pre-Class covers), Companions, Resources, Development Club, Growth Dashboard. Do not build these unless scope is revisited.

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

### Suggested build order (per ticket plan)
1. Foundations: A1, A2, B1, C1, C2
2. Profile loop end-to-end: A3 → A6 → A7
3. Pre-class loop: B2/B3 → B5 → B6/B7
4. Live-class loop: C3 → C4 → C5 → C6
5. Don't leave for later: A5, A8 (privacy review)
6. Nice-to-haves: A9, B4, B8, C7, C8

## System design (needs revision against the ticket plan — not yet fully redone)

The design below was drafted before the ticket plan and covered only a single "Socratic diagnostic + digest" flow. It substantially undersells Epic C (live real-time system) and doesn't reflect A2/A3's continuous profile-building nature (ongoing, not one diagnostic session) or B5/B6's lighter prediction-game format. Treat this section as a starting point to be reworked, not final.

**Original async flow (still roughly applicable to A2/A3 profile-building and B5/B6 pre-class)**: Student app → Conversation orchestrator → (LLM gateway + Student profile store) → downstream consumer (profile update for A3, or class-level aggregation for B6) → Teacher-facing view.

**Not yet designed**: the real-time layer for Epic C (C2 in particular) — this needs its own design pass: likely a WebSocket/pub-sub service separate from the LLM-facing orchestrator, since live engagement sync (C3, C5) has very different latency/reliability requirements than an LLM call.

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

**Technical**: curriculum content-ops lift (KSA-aligned), Arabic dialogue quality (generally weaker than English across most models — needs explicit testing, not assumed), multi-tenant data isolation, cost control at scale, classroom wifi reliability (now more critical given Epic C is real-time), mobile/tablet UX (small-screen conversational UI, voice input for younger students, shared-device session switching), and — new — real-time infrastructure reliability for Epic C (C2 is a hard dependency for C3-C6).

**Non-technical**: school procurement cycles are slow (paid trial ≠ guaranteed rollout), teacher adoption/trust (must feel like help, not surveillance — especially relevant to C3's "who's checked out" live monitoring), need real teacher/curriculum validation of B6's misconception grouping, parent/regulator trust re: AI talking to children, renewal depends on demonstrated outcomes not novelty.

**AI-specific**: keeping A2/A3 profile extraction accurate and appropriately scoped (per A8's privacy constraint on what can even be saved), PDPL/minors'-data compliance, model routing/cost, confidence-labeling logic for profile traits, hallucination risk on academic content in B2's generated lesson prep, Arabic vs English quality gap, evaluation without ground truth, safety guardrails for content aimed at minors.

## Tech Stack (confirmed 2026-09-12)

- **Language/framework**: Python + FastAPI (async end to end — all routes `async def`)
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy (async driver)
- **Migrations**: Alembic — see `.claude/skills/db-migrations/SKILL.md`
- **Testing**: pytest + pytest-asyncio + httpx.AsyncClient — see `.claude/skills/testing/SKILL.md`
- **API conventions**: see `.claude/skills/fastapi-conventions/SKILL.md`
- **Multi-tenancy**: row-level `school_id` FK on every student/teacher/school table — hard rule, not optional
- **LLM**: Claude (Haiku-class for high-volume cheap tier: A2 chat, B2 draft, B5 prompts; stronger model for lower-volume synthesis: B6 misconception summary)
- **Auth**: not yet decided — to be confirmed before A2 (first route that needs it)
- **Hosting/infra**: not yet decided — PDPL KSA data residency requirement must be resolved before first school rollout
- **Real-time (Epic C)**: not yet decided — WebSocket vs. SSE vs. third-party pub-sub; must be chosen before C2

## Notes for Claude Code

- This file should be updated as decisions get made — treat it as living project memory, not a one-time brief.
- When ticket-plan details and earlier prose descriptions conflict anywhere in this file, the ticket-plan wording wins.
- Always read `.claude/STATUS.md` at the start of a session before doing anything else — it records exactly where work stopped.
- Apply the relevant skill(s) from `.claude/skills/` for every ticket: `fastapi-conventions` when adding routes/schemas/services, `db-migrations` when touching models/tables, `testing` before marking any ticket done.