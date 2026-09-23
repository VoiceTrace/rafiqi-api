# Review questionnaire — study session / review companion

**For:** the agent continuing work on `codex/review-companion`
**Date raised:** 2026-09-23
**Answer inline** by filling the `> **Answer:**` block under each question.

---

## Before you answer

Read these three, in order:

1. `docs/review-companion.md` — the approved scope for *this branch* (a deterministic mock).
2. `docs/artifact.md` §4 — Epic D, the *full* study-session plan this mock is a step toward.
3. `AGENTS.md` — the architecture rules this repo enforces.

Two things already happened, so don't re-raise them:

- **The layering was refactored** (commit `6a07f09`). All DB access now lives in `app/services/review.py`; routes are thin and declare `response_model`; the service raises `ReviewError` instead of `HTTPException`. Wire format and status codes were verified unchanged.
- **The request-id history is now capped** at 200 entries (`REQUEST_HISTORY_LIMIT`).

The questions below are what's left. Part A is code. Part B is scope, and **B1 gates most of the rest** — answer it first.

A hard constraint on every answer: a frontend on `codex/review-companion` in `rafiki-frontend` already consumes these endpoints. Its `ReviewApiError` stores only `response.status`, and its `ReviewSession` type reads `id, lesson_id, version, lesson, mock, complete, resolved, can_hint, attempts, hint_level, current_question_id, total_questions, questions, messages`. If your answer changes any of that, say so explicitly.

---

## Part A — Open code issues

### A1 — `can_hint` hardcodes 3 hints

**Where:** `app/services/review.py:143`

```python
"can_hint": not state["complete"] and not state["resolved"] and state["hint_level"] < 3,
```

But the server-side guard that actually rejects the request reads the question:

```python
# apply_message
if state["resolved"] or state["hint_level"] >= len(question["hints"]):
    fail("no_more_hints")
```

**Current behaviour:** consistent only because every seeded question happens to have exactly 3 hints.

**Why it matters:** the moment a lesson ships a question with 2 hints, `can_hint` returns `true` at `hint_level == 2` while the server rejects the request with 409. The client renders a hint button that always errors. `docs/review-companion.md` anticipates more lessons ("Additional lessons need reviewed bilingual content and stable question IDs"), so this is a question of when, not if.

**Question:** Replace the literal with `len(questions[state["index"]]["hints"])`? If not, what enforces the 3-hint invariant on new content?

> **Answer:** Fixed in the catalog addition: can_hint now reads the current question’s hint count. A one-hint regression test covers the former mismatch.

---

### A2 — Unknown locale raises `KeyError` → 500

**Where:** `app/services/review.py:54`, `:71`, `:120`, `:126`

Every one of these indexes content by locale without checking the key exists:

```python
question = content[locale]["questions"][state["index"]]
questions = session.content[locale]["questions"]
data = content[locale]
```

**Current behaviour:** `Locale` is `Literal["en", "ar"]`, so a bad *query string* is already a 422. The exposure is content-side: a lesson row (or a session's snapshotted `content`) that lacks one of the two locales produces an unhandled `KeyError` → 500.

Sessions snapshot `content` at creation, so a session created against an English-only lesson stays permanently broken for `?locale=ar` even after the catalog is fixed.

**Question:** Which do you want — (a) validate both locales at the seed/insert boundary so bad content can't enter, (b) fall back to `en` at read time, or (c) raise a domain `ReviewError` so it surfaces as a clean 4xx instead of a 500? Note (b) changes response content for affected sessions; (a) and (c) do not.

> **Answer:** Catalog seeds validate both locales before insertion; missing lesson translations at runtime raise a domain conflict. No silent English fallback. Existing custom snapshots are not given invented translations.

---

### A3 — `chat` without `question_id` fails with a misleading code

**Where:** `app/schemas/review.py` (validator) and `app/services/review.py:58-59`

The schema requires `question_id` for three actions, but not for `chat`:

```python
if self.action in ("answer", "hint", "next") and not self.question_id:
    raise ValueError("question_id is required")
```

`chat` is then reclassified server-side, and can become `answer`:

```python
if action == "chat":
    action = "help" if is_help(message.text) or question["kind"] == "choice" \
             or state["resolved"] or state["complete"] else "answer"
```

**Current behaviour:** a `chat` that lands on a written question and doesn't trip the help detector becomes `answer`, then fails the downstream `question_required` check. The caller sent `chat`, passed schema validation, and got told a question is required.

The live client always populates `question_id` (`question_id: question?.id`), so this is latent rather than active — but it's reachable whenever `question` is undefined client-side, and by any other API consumer.

**Question:** Require `question_id` for `chat` at the schema level too, or leave it optional and return a clearer domain code? Consider that `chat` → `help` legitimately doesn't need a question, so requiring it unconditionally is stricter than the behaviour demands.

> **Answer:** Unchanged in this catalog scope. The existing frontend always sends the current question_id. A separate contract decision is still needed for other chat clients; no API behavior has been silently tightened.

---

### A4 — Idempotent replay returns *current* state, not the original response

**Where:** `app/services/review.py:232-233`

```python
if str(message.request_id) in session.state["requests"]:
    return SessionOut(**session_public(session, message.locale))
```

**Current behaviour:** replaying `request_id` X returns the session as it is *now*, not as it was when X was first applied. If X was applied at version 1 and Y then advanced to version 2, replaying X returns version 2.

`docs/review-companion.md` says: *"Replaying an accepted request returns saved state without another attempt."* That's satisfied in the sense that matters — the message is not applied twice. But a client that retried X and compared `version` against what it expected sees a different number.

The only client today retries immediately after a timeout, so in practice no other request interleaves.

**Question:** Is "not re-applied, but state may have moved on" the intended contract? If yes, say so in `docs/review-companion.md` so it isn't re-litigated. If no, storing a per-request response snapshot costs storage on a JSON column that already has two growth caps — is that trade worth it for a mock?

> **Answer:** The intended retry contract returns current session state and does not reapply retained request IDs; documented in review-companion.md. History is bounded to 200 IDs and expected_version continues to guard stale writes.

---

## Part B — Scope and business logic

### B1 — Is this mock a throwaway, or the foundation for Epic D? **(answer first)**

Everything else in Part B depends on this.

`docs/review-companion.md` positions this branch as a self-contained demo: deterministic mock, *"not reliable educational assessment"*, scores *"not written into production mastery/profile records"*, and *"Do not merge the old D1 router alongside this router: they share URL names but have different contracts."*

`docs/artifact.md` §4 defines Epic D as six tickets (D1–D6) with D3, D4 and D6 marked **Blocker**.

These are two different things wearing similar URLs. Either:

- **(a) Throwaway** — it demos, then Epic D replaces it wholesale. Then B2–B5 below are non-issues and should be closed as "out of scope by design". The cost is that sessions created during pilots carry no signal forward.
- **(b) Foundation** — Epic D grows out of this. Then the schema decisions in B2 have to be made *now*, before pilot data accumulates in a shape that can't be migrated.

**Question:** (a) or (b)? If (b), what is the migration story for `review_sessions` rows created before D3/D4 land?

> **Answer:** The user authorized the persistent catalog and concept references, with AI remaining mock. No decision was made here to declare full Epic D compatibility or throw away pilot records. This change preserves existing sessions and adds known concept metadata; production assessment migration remains a separate decision.

---

### B2 — No `concept_ref` on questions or attempts (D3 — Blocker)

`docs/artifact.md` D3: *"Attempt capture — every answer stored with correctness, the concept it targets, and a classified error type."* Acceptance criteria: *"Error types come from a defined taxonomy per subject, not free text. An attempt is never stored without a concept reference."*

**Current state:** seeded questions in `app/services/review_seed.py` carry `id, kind, text, options, answer/keywords, hints, explanation` — no `concept_ref`. Attempt events in `state["events"]` record `question_id, attempt, hint_level, assisted, score` — no concept, no error classification.

**Why it matters:** `concept_ref` is the join key between a study session and `MasteryRecord`, which is what Epic E consumes. Without it, a completed session produces no signal that reaches the rest of the product.

Note that adding `concept_ref` to the *question content* is close to free right now — it's a key in a JSON blob and a line in the seed. Adding it after sessions exist means backfilling snapshotted `content` on every historical row.

**Question:** If B1 is (b), should `concept_ref` be added to the question schema now as a forward-compatibility measure, even though nothing consumes it yet? If B1 is (a), confirm this is intentionally deferred.

> **Answer:** Added stable concept_ref to seeded questions, public questions, and saved answer/feedback events. The migration enriches existing known Newton snapshots/events without altering scores or progress. Unknown custom mappings remain absent. D3 is not complete: a subject error taxonomy and production assessment are not part of the catalog request.

---

### B3 — No `MasteryRecord` (D4 — Blocker)

`docs/artifact.md` D4: *"concept-level understanding per student. Not a grade: attempts, outcomes, and the dominant error pattern."* It is listed as the blocker for the whole of Epic E, and `.claude/STATUS.md` still carries *"D4: mastery model shape"* as an unresolved Open Decision.

**Current state:** absent. Explicitly excluded by `docs/review-companion.md`.

**Question:** This is a product-shape decision, not an implementation one, and it's blocking. Who owns it and when is it needed by? If it lands while this mock is in pilot, does the mock start writing to it, or stay isolated per B1?

> **Answer:** Still out of scope. No mastery record is written from mock scores. Product owner and delivery date are not specified by the current request.

---

### B4 — No session close or handoff (D6 — Blocker)

`docs/artifact.md` D6: *"Session close — summary card for the student, and handoff of session data to profile extraction (A3) and to D4."* Acceptance: *"a completed session measurably updates both the profile and the mastery record."*

**Current state:** `state["complete"]` is set when the last question resolves, and a `complete` event is appended. Nothing else happens. No summary card, no A3 handoff, no D4 handoff.

**Why it matters:** D6 is what closes the product loop (Study → Profile → Prep + Homework → Study). Without it the session is a terminal node — the student's work doesn't reach the teacher or the next lesson.

**Question:** Does the mock need a student-facing summary card on completion (self-contained, no handoff), or is completion deliberately a dead end until D6? The client currently shows only a flat `t("complete")` string.

> **Answer:** Completion remains the existing saved state and chat event. No summary redesign or production profile/mastery handoff was authorized in the catalog request.

---

### B5 — One session per lesson, permanently (D1 / D2)

**Where:** `app/models/review.py` — `UniqueConstraint("school_id", "student_id", "lesson_id")`

`docs/review-companion.md` states this deliberately: *"one permanent review per school/student/lesson"*, *"There is no restart/delete API in this slice."*

`docs/artifact.md` D1 asks for the opposite: *"Multiple sessions on the same lesson are distinguishable."* D2 additionally wants explicit stages (*"A stage cannot be skipped silently"*), where this mock has only a question index.

**Current state:** a student who finishes Newton's Third Law can never study it again — `create` resumes the completed session, and there's no reset path.

**Question:** For pilot use, is "review once, permanently" acceptable, or does a student re-studying before an exam need a fresh run? If a reset is needed, is it a new row (drop the unique constraint, which is a migration) or a reset-in-place endpoint (keeps the constraint, loses history)?

> **Answer:** The user explicitly chose one permanent session per school + student + lesson. Preserve the unique constraint and resume completed sessions; do not introduce resets or additional session rows.

---

## Part C — Wrap-up

### C1 — Anything above that you disagree is a real issue?

List the IDs and why. A closed question with a reason on record is more useful than a silently skipped one.

> **Answer:** B5 is an intentional user-approved scope difference from the older Epic D plan, not a catalog bug. A4 is current-state synchronization on replay, now explicitly documented. Other deferred items remain tracked rather than declared resolved.

---

### C2 — Given your answers, what is the next ticket?

Name one. If it's an Epic D blocker (B2/B3/B4), say what has to be decided by a human before code starts.

> **Answer:** Complete and verify the bilingual Subject → Chapter → Lesson catalog on top of the latest refactor. Future production D3/D4/D6 work needs the assessment, taxonomy and handoff decisions noted above.

---

## Summary table

| ID | Area | Type | Status |
|----|------|------|--------|
| A1 | `can_hint` follows content | Bug | Fixed in catalog addition |
| A2 | Missing translation handling | Bug | Seed validation + domain conflict |
| A3 | `chat` without `question_id` | Bug — misleading error | Open |
| A4 | Idempotent replay semantics | Contract | Documented current-state replay |
| B1 | Throwaway vs foundation | **Gates B2–B5** | Open |
| B2 | No `concept_ref` (D3) | Blocker — cheap now, expensive later | Open |
| B3 | No `MasteryRecord` (D4) | Blocker — product decision | Open |
| B4 | No close / handoff (D6) | Blocker | Open |
| B5 | One session per lesson (D1/D2) | Scope | Explicit user decision: permanent |
| — | DB in controller | Architecture | Fixed in `6a07f09` |
| — | No `response_model` | Architecture | Fixed in `6a07f09` |
| — | `HTTPException` in service | Architecture | Fixed in `6a07f09` |
| — | Bare-string error detail | Architecture | Fixed in `6a07f09` |
| — | Unbounded request history | Bug | Fixed in `6a07f09` |
| — | CORS missing | Config | Fixed in `6a07f09` |
