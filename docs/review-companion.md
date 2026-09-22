# Lesson review companion (mock)

Approved scope, 2026-09-22: one permanent review per school/student/lesson; objective and key points from stored bilingual content; continuous chat containing choice and written questions, feedback and progressive hints. No visible Check-In/Deepen stages. AI remains a clearly labelled deterministic mock. This implementation targets main and does not depend on the old Epic D/E feature branches.

## Storage and security

`review_lessons` contains a curated, globally available demo catalog. The migration seeds `newton-third-law` in English/Arabic. This is not a complete curriculum or a teacher authoring API. Additional lessons need reviewed bilingual content and stable question IDs. Private rubrics and unrevealed hints never appear in API responses.

`review_sessions` has a database unique constraint on school_id/student_id/lesson_id. The session UUID is an internal identity; lesson lookup is scoped to the bearer-token student and school. Creation resumes an existing record (200) or creates one (201), including races. There is no restart/delete API in this slice. Lesson content is snapshotted when a session is created so later catalog edits cannot reinterpret old answers.

Every mutation locks the session row. Clients send a UUID request_id and expected_version. Replaying an accepted request returns saved state without another attempt; stale versions return 409. Transaction rollback releases locks on failures. Keep the same request ID after an uncertain network response; reload after conflicts. A session is capped at 1000 stored events; larger histories/pagination are deferred.

## Endpoints

All require an authenticated student. Read/create locale query is `en` or `ar` (default en).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | /study-lessons | Safe lesson catalog and content. |
| GET | /study-lessons/{lesson_id} | Objective, key points and display hierarchy. |
| POST | /study-sessions | `{lesson_id}` creates or resumes. |
| GET | /study-sessions/by-lesson/{lesson_id} | Student's permanent session (404 if not started). |
| GET | /study-sessions/{id} | Conversation, safe questions and current learning state. |
| POST | /study-sessions/{id}/messages | Apply chat/answer/help/hint/next action and return complete state. |

Message fields: request_id, expected_version, action, optional question_id/text/option_id, locale. Question-scoped actions require the current question_id. Do not trust UI state: the service validates options, pending/resolved state, attempt limits, hint limits and completion. No bearer token should be passed into a frontend Client Component.

## Mock behavior

- Two seeded questions: choice, then written explanation. No AI provider dependency.
- Choice scoring uses a private answer key. Written scoring uses language-specific keyword groups, yielding 0, 0.5 or 1. This is **not** reliable educational assessment; scores remain demo feedback and are not written into production mastery/profile records.
- A correct answer or three attempts enables next. After the third unsuccessful attempt, include the explanation.
- Explicit help, questions matching the small English/Arabic help detector, and free text while a choice question is active return a canned explanation without consuming attempts. Written declarative responses are treated as answers. This limited intent heuristic is a mock limitation; the future AI provider must preserve the distinction.
- Hint requests reveal one of three levels and persist the shown level. Each attempt records hint_level and whether help was supplied. Explanations/hints stay in the transcript.
- Next after the final resolved question completes the session. Help remains available after completion.
- Authored question/objective content follows the requested locale. Historical user messages and feedback retain their original language; changing locale does not rewrite history.

Excluded: homework, teacher Q&A, timeline, self-check, notes, materials, live classes, production mastery and profile extraction. Do not merge the old D1 router alongside this router: they share URL names but have different contracts.

## Verification

Run migrations with `python -m alembic upgrade head`. The migration is reversible and uses an immutable seed fixture.

Run `python -m pytest -q`. For PostgreSQL integration/concurrency tests set REVIEW_TEST_DATABASE_URL to a **dedicated database whose name is exactly rafiqi_review_test**. Those tests recreate all tables there. Never point this variable at an application database.

Integration tests cover ownership across students/schools, creation races, stale concurrent writes, idempotent retries, persisted conversation/resume and completion across multiple questions. Unit tests cover bilingual mock scoring, hidden rubrics, hint escalation, assistance tracking and rejection without mutation.
