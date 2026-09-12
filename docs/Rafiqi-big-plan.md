# Rafeky — Big Plan (future vision, not current build scope)

This file holds the fuller, more complex version of Rafeky that the MVP (see root `CLAUDE.md`) deliberately simplifies away for now. Nothing here should be built until explicitly greenlit — this is a reference for where features are headed, not a ticket backlog.

**Do not auto-load this into every session.** Read it only when explicitly planning past the current MVP.

## Why this file exists

The MVP ticket plan (Student Profile, Pre-Class, During-Class) intentionally picked the simplest version of each feature to ship revenue-generating value fast. Several of those simplifications were deliberate trade-offs, not the end state. This file is where the "later, once the simple version is validated" layer lives.

## B5/B6 — from prediction game to full Socratic diagnostic

**MVP (current)**: structured prediction + one optional free-text "why" field. No multi-turn dialogue, no taxonomy classification, B6 is a tally of predicted outcomes.

**Big plan version**:
1. Multi-turn conversational Socratic exchange (not single prediction) — the AI asks a follow-up based on the student's stated reasoning, guiding them toward exposing their actual mental model, never stating the correct answer directly.
2. A **misconception taxonomy per topic**, built with real teacher/subject-matter input — a structured list of known wrong mental models (e.g. "conflates force-pairs with net-force cancellation"), not something the LLM invents per session.
3. Student responses get classified against that taxonomy (a second, cheaper LLM call or embedding-similarity match), not just summarized.
4. B6 becomes a real **teacher digest**: class-level aggregation of which taxonomy-tagged misconceptions are shared vs individual, plus an actionable suggestion for how to open the lesson — not just a raw tally of guesses.
5. Requires an output guard-check step to catch/regenerate any AI response that leaks the answer, since models default to being unhelpfully helpful (i.e. just answering).
6. Needs real testing against actual student phrasing (not clean test cases) — kids will try to shortcut it ("just tell me").

This is a genuine engineering step up: conversation state management, prompt-guardrail iteration, and a taxonomy-building process involving actual educators — not something to start until the simple prediction-game version has proven the underlying hypothesis (that pre-class diagnostic signal actually changes what teachers do).

## A2/A3 — richer profile building

MVP profile: traits + notes + teaching tips + per-field confidence, built from Cave chat.

Big plan additions:
- Profile traits that update not just from Cave chat but from signal across Pre-Class (B5/B6 answers) and During-Class (C3 engagement patterns, C4 question topics) — a genuinely multi-source student model, not just onboarding-chat-derived.
- Confidence decay/refresh logic — a trait "confident" six months ago on stale signal should soften over time, not sit permanently locked in.

## Epic C — richer real-time layer

MVP: live session, engagement visibility, grouped questions, push-highlights, notes.

Big plan additions:
- C7 (notes-answer-question matching) done properly — needs semantic matching between a student's own notes and their flagged questions, not a simple keyword check.
- Live sentiment/confusion signal beyond "checked out" binary — a spectrum, informed by both engagement telemetry and in-session question phrasing.
- Cross-session analytics: patterns in engagement over the term, not just per-session snapshots.

## Deferred product surface (from the original mockup, currently fully out of scope)

These screens exist in the HTML mockup but have no tickets yet — revisit only after the three current epics are validated with paying schools:

- **Homework** — tailored to level, fed by gap data from Pre-Class/During-Class once that data is trustworthy enough to drive content generation.
- **Study Cave** (beyond what Pre-Class covers) — deeper self-directed work-through-a-lesson space.
- **Companions** — teacher messaging + moderated live study rooms between students.
- **Resources** — curated materials tied to current topic.
- **Development Club** — student voice/ideas surfaced to the school.
- **Growth Dashboard** — longitudinal "how you're growing, not just your grades" view; depends on enough historical profile + engagement data to be meaningful, so naturally comes later.

## System design — the full picture

The MVP's system design is intentionally partial (see root `CLAUDE.md`'s system design section, itself flagged as needing rework post-ticket-plan). The full picture, once Socratic diagnostic + digest + homework personalization are all real:

**Full async flow**: Student app → Conversation orchestrator → (LLM gateway + Student profile store + Curriculum/misconception-taxonomy service) → Digest generator (stronger model, post-session) → Teacher dashboard. Separately: Digest → Homework personalizer → back to Student app.

**Real-time flow** (Epic C, still needed even at MVP): Student/teacher app ↔ WebSocket/pub-sub live-session service ↔ session state store, with a lock-on-session-end step (C8) feeding the async side once class ends.

**Model routing** at full scale: cheap/fast tier for all per-turn dialogue (Cave chat, prediction follow-ups, live-session chat if added), stronger tier reserved for digest generation and any lesson-prep synthesis that needs real reasoning quality. Cost math should be revisited at each scale milestone (pilot → 3 schools → beyond), not assumed static.

## Non-technical challenges that apply more as this grows

- Misconception taxonomy needs ongoing teacher/curriculum validation, not a one-time build — it's a maintained asset, and maintaining it is real, recurring work.
- The more the profile model knows about a student (Big Plan multi-source version), the more PDPL/parent-trust scrutiny it invites — re-run the privacy review (A8-equivalent) at each expansion of what's collected, not just once at MVP launch.
- "AI tutor" category crowding gets more relevant as more mockup screens ship — the differentiator stays the teacher-facing structured insight (Pre-Class/During-Class data feeding real pedagogical action), not chat novelty.