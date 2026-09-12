---
name: fastapi-conventions
description: Use whenever adding or editing an API route, Pydantic schema, or service function in rafiqi-api. Covers folder structure, request/response shape, error handling, and auth pattern for this project.
---

# Rafiqi API conventions

## Folder structure
```
app/
  api/
    routes/        # one file per resource, e.g. profiles.py, sessions.py
    deps.py        # shared FastAPI dependencies (auth, db session, etc.)
  models/           # SQLAlchemy models (DB tables)
  schemas/          # Pydantic models (request/response shapes) — never reuse
                     # a SQLAlchemy model directly as a response schema
  services/         # business logic — routes stay thin, call into services
  core/             # config, security, startup/shutdown
  main.py
alembic/            # migrations — see the db-migrations skill
tests/
```

## Route conventions
- Every route function is thin: parse input (Pydantic does this), call a
  service function, return. No business logic inline in the route.
- Every route has an explicit `response_model`. Never return a raw dict or
  ORM object directly.
- Use `async def` for all routes — this project is async end to end
  (Supabase/Postgres via an async driver). Don't mix sync route functions
  in without a specific reason, and note the reason in a comment if you do.

## Error handling
- Raise `HTTPException` from routes/services with a consistent error body:
  `{"error": {"code": "...", "message": "..."}}` — don't return ad-hoc
  error shapes per endpoint.
- Define known error codes as an enum in `app/core/errors.py` rather than
  inventing string literals per route.

## Auth
- Auth is enforced via a FastAPI dependency (`app/api/deps.py`), not
  checked manually inside each route.
- Every route must declare which roles can access it explicitly — never
  assume a route is "obviously" teacher-only or student-only without the
  dependency stating it.

## Multi-tenancy (per school)
- Every query that touches student/teacher/school data must be scoped to
  the requesting user's school. This is a hard rule given PDPL — if you're
  writing a query and it's not obviously scoped, stop and flag it rather
  than assuming it's fine.

## Before marking a ticket done
- Route has a response_model, is scoped to the right auth dependency, and
  any DB query is school-scoped where applicable.
