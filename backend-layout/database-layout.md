# Database layout

Source commit: `ad0717cefe31da9b797e1234d94f887a15fde07a`. Migration head: `83bcb2215849`.

This is the schema reconstructed from committed migration DDL, cross-checked against ORM metadata. It is not a live database inspection.

PK = primary key; FK = foreign key; UK = individually unique. Composite uniqueness is listed separately. All timestamps are timezone-aware. FLOAT is PostgreSQL double precision unless a precision is specified.

## review_subjects

Global bilingual subject catalog, shared across schools.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `VARCHAR(100)` | no | PK | `—` | `—` |
| `title` | `JSON` | no | — | `—` | `—` |

Constraints and indexes:

- `unnamed`: PRIMARY KEY (id).

## schools

Tenant root: school identity.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `name` | `VARCHAR(255)` | no | — | `—` | `—` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `unnamed`: PRIMARY KEY (id).

## review_chapters

Global bilingual chapters belonging to subjects.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `VARCHAR(100)` | no | PK | `—` | `—` |
| `subject_id` | `VARCHAR(100)` | no | FK | `—` | `—` |
| `title` | `JSON` | no | — | `—` | `—` |

Constraints and indexes:

- `unnamed`: FK (subject_id) → review_subjects.id; ON DELETE NO ACTION.
- `unnamed`: PRIMARY KEY (id).
- `ix_review_chapters_subject_id`: INDEX (subject_id).

## users

Teachers and students share one table; email is globally unique. Deactivation sets is_active=false.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `email` | `VARCHAR(255)` | no | UK | `—` | `—` |
| `full_name` | `VARCHAR(255)` | no | — | `—` | `—` |
| `role` | `VARCHAR(20)` | no | — | `—` | `—` |
| `hashed_password` | `VARCHAR(255)` | no | — | `—` | `—` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |
| `is_active` | `BOOLEAN` | no | — | `true` | `—` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |
| `avatar_url` | `TEXT` | yes | — | `—` | `—` |

Constraints and indexes:

- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `unnamed`: UNIQUE (email).
- `ix_users_school_id`: INDEX (school_id).

## conversations

Lightweight Cave-session scaffold. Does not store messages and has no mounted conversation API.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `student_id` | `UUID` | no | FK | `—` | `—` |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |
| `ended_at` | `TIMESTAMP WITH TIME ZONE` | yes | — | `—` | `—` |

Constraints and indexes:

- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: FK (student_id) → users.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `ix_conversations_school_id`: INDEX (school_id).
- `ix_conversations_student_id`: INDEX (student_id).

## mastery_records

Recomputable concept mastery by school, student and subject.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `student_id` | `UUID` | no | FK | `—` | `—` |
| `subject_id` | `VARCHAR(100)` | no | FK | `—` | `—` |
| `concept_ref` | `VARCHAR(100)` | no | — | `—` | `—` |
| `mastery_score` | `FLOAT` | no | — | `—` | `—` |
| `mastery_band` | `VARCHAR(20)` | no | — | `—` | `—` |
| `evidence_count` | `INTEGER` | no | — | `—` | `—` |
| `attempt_count` | `INTEGER` | no | — | `—` | `—` |
| `assisted_evidence_count` | `INTEGER` | no | — | `—` | `—` |
| `dominant_error_type` | `VARCHAR(100)` | yes | — | `—` | `—` |
| `calculation_version` | `VARCHAR(20)` | no | — | `—` | `mvp-v1` |
| `last_attempt_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `—` | `—` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `ck_mastery_assisted_count`: CHECK assisted_evidence_count >= 0 AND assisted_evidence_count <= evidence_count.
- `ck_mastery_attempt_count`: CHECK attempt_count >= evidence_count.
- `ck_mastery_band`: CHECK mastery_band IN ('needs_support', 'developing', 'secure').
- `ck_mastery_evidence_count`: CHECK evidence_count >= 1.
- `ck_mastery_score`: CHECK mastery_score >= 0 AND mastery_score <= 1.
- `unnamed`: FK (student_id) → users.id; ON DELETE CASCADE.
- `unnamed`: FK (subject_id) → review_subjects.id; ON DELETE NO ACTION.
- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `uq_mastery_student_concept`: UNIQUE (school_id, student_id, subject_id, concept_ref).
- `ix_mastery_records_school_id`: INDEX (school_id).
- `ix_mastery_records_student_id`: INDEX (student_id).
- `ix_mastery_records_subject_id`: INDEX (subject_id).

## refresh_tokens

Hashed refresh-token credentials, expiry and revocation; tenant ownership is indirect through users.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `user_id` | `UUID` | no | FK | `—` | `—` |
| `token_hash` | `VARCHAR(64)` | no | UK | `—` | `—` |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `—` | `—` |
| `revoked_at` | `TIMESTAMP WITH TIME ZONE` | yes | — | `—` | `—` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `unnamed`: FK (user_id) → users.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `ix_refresh_tokens_token_hash`: UNIQUE INDEX (token_hash).
- `ix_refresh_tokens_user_id`: INDEX (user_id).

## review_lessons

Global lessons with bilingual JSON content, concepts, questions and private rubrics.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `VARCHAR(100)` | no | PK | `—` | `—` |
| `content` | `JSON` | no | — | `—` | `—` |
| `chapter_id` | `VARCHAR(100)` | no | FK | `—` | `—` |

Constraints and indexes:

- `fk_review_lesson_chapter`: FK (chapter_id) → review_chapters.id; ON DELETE NO ACTION.
- `unnamed`: PRIMARY KEY (id).
- `ix_review_lessons_chapter_id`: INDEX (chapter_id).

## student_profiles

Optional one-to-one profile anchor for a user; no dedicated profile endpoint is currently mounted.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `student_id` | `UUID` | no | FK, UK | `—` | `—` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: FK (student_id) → users.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `unnamed`: UNIQUE (student_id).
- `ix_student_profiles_school_id`: INDEX (school_id).

## profile_traits

Profile preferences/goals, confidence and optional conversation provenance; no mounted trait API.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `profile_id` | `UUID` | no | FK | `—` | `—` |
| `source_conversation_id` | `UUID` | yes | FK | `—` | `—` |
| `category` | `VARCHAR(50)` | no | — | `—` | `—` |
| `trait_key` | `VARCHAR(100)` | no | — | `—` | `—` |
| `title` | `VARCHAR(255)` | no | — | `—` | `—` |
| `description` | `TEXT` | no | — | `—` | `—` |
| `teaching_tip` | `TEXT` | yes | — | `—` | `—` |
| `score` | `FLOAT` | no | — | `0.0` | `0.0` |
| `confidence` | `VARCHAR(20)` | no | — | `still_forming` | `still_forming` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `unnamed`: FK (source_conversation_id) → conversations.id; ON DELETE SET NULL.
- `unnamed`: FK (profile_id) → student_profiles.id; ON DELETE CASCADE.
- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `ix_profile_traits_profile_id`: INDEX (profile_id).
- `ix_profile_traits_school_id`: INDEX (school_id).

## review_sessions

One persistent review per school/student/lesson; lesson snapshot and conversation state are JSON.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `student_id` | `UUID` | no | FK | `—` | `—` |
| `lesson_id` | `VARCHAR(100)` | no | FK | `—` | `—` |
| `content` | `JSON` | no | — | `—` | `—` |
| `state` | `JSON` | no | — | `—` | `—` |
| `version` | `INTEGER` | no | — | `0` | `0` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `unnamed`: FK (student_id) → users.id; ON DELETE CASCADE.
- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: FK (lesson_id) → review_lessons.id; ON DELETE NO ACTION.
- `unnamed`: PRIMARY KEY (id).
- `uq_review_student_lesson`: UNIQUE (school_id, student_id, lesson_id).

## review_attempts

Persisted answer evidence, assessment score, assistance and error taxonomy.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `student_id` | `UUID` | no | FK | `—` | `—` |
| `session_id` | `UUID` | no | FK | `—` | `—` |
| `lesson_id` | `VARCHAR(100)` | no | FK | `—` | `—` |
| `request_id` | `UUID` | no | — | `—` | `—` |
| `question_id` | `VARCHAR(100)` | no | — | `—` | `—` |
| `concept_ref` | `VARCHAR(100)` | no | — | `—` | `—` |
| `response_text` | `TEXT` | no | — | `—` | `—` |
| `option_id` | `VARCHAR(100)` | yes | — | `—` | `—` |
| `correctness_score` | `FLOAT` | no | — | `—` | `—` |
| `error_type` | `VARCHAR(100)` | yes | — | `—` | `—` |
| `hint_level` | `INTEGER` | no | — | `—` | `—` |
| `assisted` | `BOOLEAN` | no | — | `—` | `—` |
| `attempt_number` | `INTEGER` | no | — | `—` | `—` |
| `locale` | `VARCHAR(2)` | no | — | `—` | `—` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `ck_review_attempt_error_type`: CHECK error_type IS NULL OR error_type IN ('force_pair_unequal_magnitude', 'force_pair_missing_reaction', 'force_pair_incomplete_distinct_objects', 'force_pair_missing_distinct_objects', 'balanced_force_means_stopped', 'kinetic_energy_requires_motion', 'equivalent_fraction_denominator_only').
- `ck_review_attempt_hint_level`: CHECK hint_level >= 0.
- `ck_review_attempt_number`: CHECK attempt_number >= 1.
- `ck_review_attempt_score`: CHECK correctness_score >= 0 AND correctness_score <= 1.
- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: FK (session_id) → review_sessions.id; ON DELETE CASCADE.
- `unnamed`: FK (lesson_id) → review_lessons.id; ON DELETE NO ACTION.
- `unnamed`: FK (student_id) → users.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `uq_review_attempt_session_request`: UNIQUE (session_id, request_id).
- `ix_review_attempts_school_id`: INDEX (school_id).
- `ix_review_attempts_session_id`: INDEX (session_id).
- `ix_review_attempts_student_id`: INDEX (student_id).

## review_session_summaries

One immutable application-level completion snapshot per session; localized at read time.

| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |
|---|---|---|---|---|---|
| `id` | `UUID` | no | PK | `—` | `uuid4()` |
| `school_id` | `UUID` | no | FK | `—` | `—` |
| `student_id` | `UUID` | no | FK | `—` | `—` |
| `session_id` | `UUID` | no | FK, UK | `—` | `—` |
| `lesson_id` | `VARCHAR(100)` | no | FK | `—` | `—` |
| `concepts` | `JSON` | no | — | `—` | `—` |
| `total_attempts` | `INTEGER` | no | — | `—` | `—` |
| `calculation_version` | `VARCHAR(20)` | no | — | `—` | `—` |
| `completed_at` | `TIMESTAMP WITH TIME ZONE` | no | — | `now()` | `—` |

Constraints and indexes:

- `ck_review_summary_attempts`: CHECK total_attempts >= 1.
- `unnamed`: FK (school_id) → schools.id; ON DELETE CASCADE.
- `unnamed`: FK (lesson_id) → review_lessons.id; ON DELETE NO ACTION.
- `unnamed`: FK (student_id) → users.id; ON DELETE CASCADE.
- `unnamed`: FK (session_id) → review_sessions.id; ON DELETE CASCADE.
- `unnamed`: PRIMARY KEY (id).
- `uq_review_summary_session`: UNIQUE (session_id).
- `ix_review_session_summaries_school_id`: INDEX (school_id).
- `ix_review_session_summaries_student_id`: INDEX (student_id).
