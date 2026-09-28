# Rafiqi backend: architecture and database

Generated from source commit `ad0717cefe31da9b797e1234d94f887a15fde07a` on 2026-09-25 (initial baseline: latest `main`).

Scope: **13 application tables, 99 columns, 25 foreign keys, 25 API operations, 9 migrations**. PostgreSQL 16 is the local Compose target.

## Files

- [Complete architecture assessment](architecture-review.md)
- [Rendered diagrams](rendered/README.md)
- [Complete database dictionary](database-layout.md)
- [PostgreSQL schema SQL](database-schema.sql)
- [Machine-readable schema](database-schema.json)
- [Implemented API inventory](api-layout.md)
- [JSON structures and behavior](json-and-behavior.md)

## Evidence and boundaries

The schema was reconstructed from migration declarations without running their data operations, then checked against SQLAlchemy models for tables, columns, types, nullability, foreign keys, unique constraints, checks and indexes. SQL is reference DDL; deploy with Alembic so catalog seed data and version history are applied. The Alembic-owned `alembic_version` bookkeeping table is not one of the 13 application tables. No live database was inspected or modified.

The checked-in generator can refresh these files with the backend Python environment: `python scripts/generate_backend_layout.py`. Diagrams describe implemented behavior, rather than future product-plan features. Each diagram is also supplied as editable `.mmd` source.

## Backend architecture

[Mermaid source](backend-architecture.mmd)

```mermaid
flowchart TB
    Client["Teacher or student client"] --> CORS["FastAPI / CORS middleware"]
    CORS --> Auth["Auth routes: login, refresh, logout"]
    CORS --> JWT["Bearer JWT dependency: user ID, school ID, role"]
    JWT --> Users["User routes: own account and teacher-managed users"]
    JWT --> Review["Student-only catalog and study review routes"]
    Auth --> AuthSvc["auth service / password and token helpers"]
    Users --> UserSvc["user service"]
    Review --> Catalog["review_catalog service"]
    Review --> ReviewSvc["review service / deterministic assessment"]
    ReviewSvc --> Assessment["review_assessment: concept error taxonomy"]
    AuthSvc --> Session["SQLAlchemy AsyncSession / explicit commits"]
    UserSvc --> Session
    Catalog --> Session
    ReviewSvc --> Session
    Session --> DB[("PostgreSQL / 13 application tables")]
    UserSvc --> Files["Local media/avatars files"]
    CORS --> Static["Public /media static mount"]
    Static --> Files
    CORS --> Health["GET /health: process status"]
    CORS --> Docs["OpenAPI / Swagger / ReDoc"]
    Alembic["Alembic: 9 committed migrations and seed fixtures"] --> DB
    Seed["Development seed and review catalog loaders"] --> DB
    Config["Environment settings"] -.-> CORS
    Config -.-> Session
    Schemas["Pydantic request and response schemas"] -.-> Users
    Schemas -.-> Review
    Schemas -.-> Auth
```

## Complete entity relationship diagram

[Mermaid source](database-erd.mmd)

```mermaid
erDiagram
    review_subjects {
        varchar(100) id PK "required"
        json title "required"
    }
    schools {
        uuid id PK "required"
        varchar(255) name "required"
        timestamp_with_time_zone created_at "required"
    }
    review_chapters {
        varchar(100) id PK "required"
        varchar(100) subject_id FK "required"
        json title "required"
    }
    review_subjects ||..o{ review_chapters : "subject_id"
    users {
        uuid id PK "required"
        uuid school_id FK "required"
        varchar(255) email UK "required"
        varchar(255) full_name "required"
        varchar(20) role "required"
        varchar(255) hashed_password "required"
        timestamp_with_time_zone created_at "required"
        boolean is_active "required"
        timestamp_with_time_zone updated_at "required"
        text avatar_url "nullable"
    }
    schools ||..o{ users : "school_id"
    conversations {
        uuid id PK "required"
        uuid school_id FK "required"
        uuid student_id FK "required"
        timestamp_with_time_zone started_at "required"
        timestamp_with_time_zone ended_at "nullable"
    }
    schools ||..o{ conversations : "school_id"
    users ||..o{ conversations : "student_id"
    mastery_records {
        uuid id PK "required"
        uuid school_id FK "required"
        uuid student_id FK "required"
        varchar(100) subject_id FK "required"
        varchar(100) concept_ref "required"
        float mastery_score "required"
        varchar(20) mastery_band "required"
        integer evidence_count "required"
        integer attempt_count "required"
        integer assisted_evidence_count "required"
        varchar(100) dominant_error_type "nullable"
        varchar(20) calculation_version "required"
        timestamp_with_time_zone last_attempt_at "required"
        timestamp_with_time_zone created_at "required"
        timestamp_with_time_zone updated_at "required"
    }
    schools ||..o{ mastery_records : "school_id"
    users ||..o{ mastery_records : "student_id"
    review_subjects ||..o{ mastery_records : "subject_id"
    refresh_tokens {
        uuid id PK "required"
        uuid user_id FK "required"
        varchar(64) token_hash UK "required"
        timestamp_with_time_zone expires_at "required"
        timestamp_with_time_zone revoked_at "nullable"
        timestamp_with_time_zone created_at "required"
    }
    users ||..o{ refresh_tokens : "user_id"
    review_lessons {
        varchar(100) id PK "required"
        json content "required"
        varchar(100) chapter_id FK "required"
    }
    review_chapters ||..o{ review_lessons : "chapter_id"
    student_profiles {
        uuid id PK "required"
        uuid school_id FK "required"
        uuid student_id FK,UK "required"
        timestamp_with_time_zone created_at "required"
        timestamp_with_time_zone updated_at "required"
    }
    schools ||..o{ student_profiles : "school_id"
    users ||..o| student_profiles : "student_id"
    profile_traits {
        uuid id PK "required"
        uuid school_id FK "required"
        uuid profile_id FK "required"
        uuid source_conversation_id FK "nullable"
        varchar(50) category "required"
        varchar(100) trait_key "required"
        varchar(255) title "required"
        text description "required"
        text teaching_tip "nullable"
        float score "required"
        varchar(20) confidence "required"
        timestamp_with_time_zone updated_at "required"
    }
    student_profiles ||..o{ profile_traits : "profile_id"
    schools ||..o{ profile_traits : "school_id"
    conversations |o..o{ profile_traits : "source_conversation_id"
    review_sessions {
        uuid id PK "required"
        uuid school_id FK "required"
        uuid student_id FK "required"
        varchar(100) lesson_id FK "required"
        json content "required"
        json state "required"
        integer version "required"
        timestamp_with_time_zone created_at "required"
        timestamp_with_time_zone updated_at "required"
    }
    review_lessons ||..o{ review_sessions : "lesson_id"
    schools ||..o{ review_sessions : "school_id"
    users ||..o{ review_sessions : "student_id"
    review_attempts {
        uuid id PK "required"
        uuid school_id FK "required"
        uuid student_id FK "required"
        uuid session_id FK "required"
        varchar(100) lesson_id FK "required"
        uuid request_id "required"
        varchar(100) question_id "required"
        varchar(100) concept_ref "required"
        text response_text "required"
        varchar(100) option_id "nullable"
        float correctness_score "required"
        varchar(100) error_type "nullable"
        integer hint_level "required"
        boolean assisted "required"
        integer attempt_number "required"
        varchar(2) locale "required"
        timestamp_with_time_zone created_at "required"
    }
    review_lessons ||..o{ review_attempts : "lesson_id"
    schools ||..o{ review_attempts : "school_id"
    review_sessions ||..o{ review_attempts : "session_id"
    users ||..o{ review_attempts : "student_id"
    review_session_summaries {
        uuid id PK "required"
        uuid school_id FK "required"
        uuid student_id FK "required"
        uuid session_id FK,UK "required"
        varchar(100) lesson_id FK "required"
        json concepts "required"
        integer total_attempts "required"
        varchar(20) calculation_version "required"
        timestamp_with_time_zone completed_at "required"
    }
    review_lessons ||..o{ review_session_summaries : "lesson_id"
    schools ||..o{ review_session_summaries : "school_id"
    review_sessions ||..o| review_session_summaries : "session_id"
    users ||..o{ review_session_summaries : "student_id"
```

## Authentication

[Mermaid source](authentication-flow.mmd)

```mermaid
sequenceDiagram
    actor Client
    participant API as Auth routes
    participant Service as Auth service
    participant DB as PostgreSQL
    Client->>API: POST /auth/login (email, password)
    API->>Service: login
    Service->>DB: Find user by globally unique email
    Note over Service: Verify password and is_active
    Service->>DB: Insert hashed refresh token and commit
    Service-->>Client: Access JWT and raw refresh token
    Client->>API: POST /auth/refresh (raw refresh token)
    API->>Service: refresh_access_token
    Service->>DB: Look up token hash and user
    Note over Service: Check expiry, revocation and active user
    Service->>DB: Revoke old token and commit
    Service->>DB: Insert new hashed token and commit
    Service-->>Client: New access JWT and refresh token
    Client->>API: POST /auth/logout (raw refresh token)
    API->>Service: logout
    Service->>DB: Revoke token if still active, commit when changed
    API-->>Client: 204
    Note over Client,Service: Already-issued access JWT remains valid until expiry
```

## Review persistence flow

[Mermaid source](review-flow.mmd)

```mermaid
sequenceDiagram
    actor Student
    participant API as Student-only routes
    participant Service as Review service
    participant DB as PostgreSQL
    Student->>API: POST /study-sessions (lesson_id)
    API->>Service: create_or_resume_session (token user and school)
    Service->>DB: Find session by school, student and lesson
    alt Existing session
        Service-->>Student: Resume session (200)
    else New session
        Service->>DB: Read lesson, insert content snapshot and initial state, commit
        Service-->>Student: New session (201)
    end
    Student->>API: POST messages (request_id, expected_version, action, locale)
    API->>Service: process_message
    Service->>DB: SELECT owned session FOR UPDATE
    alt Request ID already in recent history
        Service-->>Student: Current session, no mutation
    else Version mismatch
        Service-->>Student: 409 stale_session
    else Valid request
        Note over Service: Validate action and question, apply deterministic state transition
        opt Action produces an answer
            Service->>DB: Insert attempt, flush
            Service->>DB: Read concept evidence, upsert mastery
        end
        opt Transition to complete
            Service->>DB: Recalculate concept mastery and insert one completion summary
        end
        Service->>DB: Commit state, version and evidence together, refresh session
        Service-->>Student: Safe localized session projection and optional summary
    end
```

## Review state transitions

[Mermaid source](review-state.mmd)

```mermaid
stateDiagram-v2
    [*] --> AwaitingAnswer: create review
    AwaitingAnswer --> AwaitingAnswer: hint or help / assistance true
    AwaitingAnswer --> AwaitingAnswer: incorrect or partial answer / fewer than 3 attempts
    AwaitingAnswer --> Resolved: score equals 1 or third attempt
    Resolved --> Resolved: help
    Resolved --> AwaitingAnswer: next / more questions; reset question counters
    Resolved --> Complete: next / last question; save summary
    Complete --> Complete: help / summary remains unchanged
    note right of AwaitingAnswer
        chat maps to help or answer
        state is stored inside JSON
        invalid or stale actions return errors
    end note
```

## Migration history

[Mermaid source](migration-history.mmd)

```mermaid
flowchart LR
    m0["ef81a87bd4aa<br/>a1_initial_schema"]
    m1["b2c4f1a8e390<br/>a_user_add_is_active_updated_at"]
    m0 --> m1
    m2["c3d5f1a8b290<br/>a_user_add_avatar_url"]
    m1 --> m2
    m3["d4e6a2c9f1b7<br/>a_user_add_refresh_tokens"]
    m2 --> m3
    m4["e5a1b2c3d4e5<br/>review_companion"]
    m3 --> m4
    m5["f6b2c3d4e5f6<br/>review_catalog"]
    m4 --> m5
    m6["a7c3d4e5f6a7<br/>review_attempt_taxonomy"]
    m5 --> m6
    m7["6d9fe6080e14<br/>d4_add_mastery_records"]
    m6 --> m7
    m8["83bcb2215849<br/>d6_add_review_session_summaries"]
    m7 --> m8
```
