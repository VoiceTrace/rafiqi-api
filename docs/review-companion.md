# Lesson review companion (mock)

Approved scope, 2026-09-22: one permanent review per school/student/lesson; objective and key points from stored bilingual content; continuous chat containing choice and written questions, feedback and progressive hints. No visible Check-In/Deepen stages. AI remains a clearly labelled deterministic mock. This implementation targets main and does not depend on the old Epic D/E feature branches.

## Storage and security

`review_lessons` contains a curated, globally available demo catalog. The migrations seed four English/Arabic lessons across two subjects and three chapters; see the catalog contract below. This is not a complete curriculum or a teacher authoring API. Additional lessons need reviewed bilingual content and stable question IDs. Private rubrics and unrevealed hints never appear in API responses.

`review_sessions` has a database unique constraint on school_id/student_id/lesson_id. The session UUID is an internal identity; lesson lookup is scoped to the bearer-token student and school. Creation resumes an existing record (200) or creates one (201), including races. There is no restart/delete API in this slice. Lesson content is snapshotted when a session is created so later catalog edits cannot reinterpret old answers.

Every mutation locks the session row. Clients send a UUID request_id and expected_version. Replaying one of the most recent 200 accepted request IDs returns the current saved session state (not the historical response) without another attempt; stale versions return 409. Transaction rollback releases locks on failures. Keep the same request ID after an uncertain network response; reload after conflicts. A session is capped at 1000 stored events; larger histories/pagination are deferred.

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

`chat` may omit `question_id` when it is a help request. If its text is instead treated as a written answer, the API returns a structured `409` conflict with `Chat question id required`; it does not misreport the request as an ordinary question-scoped action.

## Mock behavior

- Newton has a choice question followed by a written explanation. The other demo lessons each have a concept-specific choice question. No AI provider dependency.
- Choice scoring uses a private answer key. Written scoring uses language-specific keyword groups, yielding 0, 0.5 or 1. This is **not** reliable educational assessment; scores remain demo feedback and are not written into production mastery/profile records.
- A correct answer or three attempts enables next. After the third unsuccessful attempt, include the explanation.
- Explicit help, questions matching the small English/Arabic help detector, and free text while a choice question is active return a canned explanation without consuming attempts. Written declarative responses are treated as answers. This limited intent heuristic is a mock limitation; the future AI provider must preserve the distinction.
- Hint requests reveal one of the question’s stored levels and persist the shown level. Each attempt records hint_level and whether help was supplied. Explanations/hints stay in the transcript.
- Next after the final resolved question completes the session. Help remains available after completion.
- Authored question/objective content follows the requested locale. Historical user messages and feedback retain their original language; changing locale does not rewrite history.

Excluded: homework, teacher Q&A, timeline, self-check, notes, materials, live classes, production mastery and profile extraction. Do not merge the old D1 router alongside this router: they share URL names but have different contracts.

## Verification

Run migrations with `python -m alembic upgrade head`. The migration is reversible and uses an immutable seed fixture.

Run `python -m pytest -q`. For PostgreSQL integration/concurrency tests set REVIEW_TEST_DATABASE_URL to a **dedicated database whose name is exactly rafiqi_review_test**. Those tests recreate all tables there. Never point this variable at an application database.

Integration tests cover ownership across students/schools, creation races, stale concurrent writes, idempotent retries, persisted conversation/resume and completion across multiple questions. Unit tests cover bilingual mock scoring, hidden rubrics, hint escalation, assistance tracking and rejection without mutation.

## Subject → Chapter → Lesson catalog (2026-09-23)

This addition follows the architecture refactor in `6a07f09`: thin routes, typed response models, domain errors, and service-owned database access. Catalog tables are global, read-only through this API, and contain no student data. Sessions remain scoped to authenticated school/student.

| Method | Path | Response |
| --- | --- | --- |
| GET | `/study-subjects?locale=en` | `[{id, title}]` |
| GET | `/study-subjects/{subject_id}/chapters?locale=ar` | `[{id, subject_id, title}]` |
| GET | `/study-lessons?chapter_id={chapter_id}&locale=en` | Localized lesson array filtered by chapter |
| GET | `/study-lessons/{lesson_id}?locale=ar` | One localized lesson |

All catalog endpoints require the existing student authentication. IDs are language-independent. Unknown subject/chapter/lesson returns structured 404, invalid locale returns 422. A valid parent with no children returns `[]`. Omitting `chapter_id` retains the existing full-catalog endpoint for compatibility.

Lesson responses retain all existing fields and add `subject_id`, `chapter_id`, and `concept_refs: [{id, title, description}]`. Each seeded question contains `concept_ref`; public questions and newly saved answer/feedback events include it. Concept references describe curriculum targets, not mastery scores or classified errors. Existing custom lessons without known concept mappings retain empty references rather than invented historical classifications.

The relational chain is `review_subjects.id ← review_chapters.subject_id`, then `review_chapters.id ← review_lessons.chapter_id`, then `review_lessons.id ← review_sessions.lesson_id`. Foreign keys enforce parent existence; the existing school/student/lesson uniqueness constraint is unchanged. Localized content and concept references live in the lesson JSON and are snapshotted into sessions.

### Demo seed

| Subject ID | Chapter ID | Lesson ID |
| --- | --- | --- |
| physics | forces-motion | newton-third-law |
| physics | forces-motion | balanced-forces |
| physics | energy | kinetic-energy |
| mathematics | fractions | equivalent-fractions |

`alembic upgrade head` creates and populates the catalog. Migration `f6b2c3d4e5f6` adds metadata to existing Newton snapshots/attempts without rewriting questions, scores, requests, progress or UUIDs. Unrecognized existing lessons receive stable legacy parent IDs, preserving their content. Downgrade removes hierarchy tables/columns but intentionally retains seeded lessons and snapshot metadata to avoid deleting student work; re-upgrade is supported. Run migrations with API writes stopped.

`scripts/seed.py` includes the catalog. `python scripts/seed.py --catalog-only` safely reruns only the catalog seed using insert-on-conflict-do-nothing. It preserves edited content and all sessions. The seed validates both locales and concept references before inserting; no live AI runs. The immutable migration fixture and application seed are tested for equality. Unknown/missing lesson translations return a domain conflict rather than silent English fallback.

### End-to-end sequence

1. Load subjects; chapter and lesson are initially unselected and disabled.
2. Choose a subject, then fetch its chapters. Changing subject clears chapter/lesson.
3. Choose a chapter, then fetch its lessons. Changing chapter clears lesson.
4. Choose a lesson; load its content and look up the authenticated student's session by lesson ID.
5. Start creates/resumes the same UUID; answers, help and hints save through the existing messages endpoint.
6. Switch lessons and return: restore that lesson's separate saved state. Direct lesson URLs resolve their parent IDs.

Mock AI, production mastery/profile handoff, error taxonomy, repeat study runs and authoring APIs remain outside this catalog slice. One permanent session per school/student/lesson remains the explicit user decision.

Catalog validation: 65 tests passed with PostgreSQL enabled, including hierarchy filtering, bilingual IDs, concept capture, ownership/concurrency, seed reruns, and migration preservation through upgrade/downgrade/re-upgrade.
