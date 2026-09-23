---
name: python-architecture
description: Load when reviewing, writing, or refactoring any Python file in rafiqi-api. Enforces the three-layer architecture and catches the specific patterns that agent-generated code (Codex, etc.) tends to violate. Use together with fastapi-conventions.
---

# Python architecture — rafiqi-api

## The three layers and their hard boundaries

```
Route  (app/api/routes/)   ← parse input, call service, return schema
  ↓
Service (app/services/)    ← business logic + ALL DB access
  ↓
DB     (PostgreSQL via SQLAlchemy async)
```

### What kills a code review immediately

| Violation | Why it matters |
|-----------|---------------|
| SQLAlchemy call inside a route function | Routes become untestable; business logic is hidden in the HTTP layer |
| `HTTPException` raised inside a service | Services become HTTP-coupled; impossible to reuse in background tasks, CLIs, or tests without a request context |
| Query missing `school_id` in WHERE clause | PDPL violation — data from one school leaks to another |
| Route missing `response_model=` | FastAPI can't validate or document the response; client gets an undocumented dict |
| Bare string in HTTPException `detail` | Breaks the project error contract; client parsers break |
| ORM object returned from service | SQLAlchemy expires ORM objects after commit, triggering lazy loads → `MissingGreenlet` crashes |

---

## Pattern: DB query helper in a route file

Codex frequently generates a local async helper in the route file that runs a DB query, then calls it from multiple route functions. This pattern looks like:

```python
# BAD — query helper living in the route file
async def owned(db, user, session_id=None):
    stmt = select(MySession).where(...)
    return (await db.execute(stmt)).scalar_one_or_none()

@router.get("/{id}")
async def get_thing(id: uuid.UUID, user: Student, db: DB):
    session = await owned(db, user, session_id=id)
    ...
```

**Fix**: move `owned` to the service module and give it a descriptive name:

```python
# CORRECT — in app/services/my_feature.py
async def get_session_for_student(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    session_id: uuid.UUID,
    lock: bool = False,
) -> MySession | None:
    stmt = select(MySession).where(
        MySession.id == session_id,
        MySession.student_id == student_id,
        MySession.school_id == school_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()
```

---

## Pattern: business logic in the route body

```python
# BAD — branching on model state in the route
@router.post("/{id}/messages")
async def send_message(id: uuid.UUID, body: MessageIn, user: Student, db: DB):
    session = await owned(db, user, session_id=id, lock=True)
    if str(body.request_id) in session.state["requests"]:   # ← business logic
        return session_public(session, body.locale)
    if session.version != body.expected_version:             # ← business logic
        raise HTTPException(409, "stale_session")
    session.state = apply_message(...)                       # ← business logic
    session.version += 1                                     # ← business logic
    await db.commit()                                        # ← DB in route
    ...
```

**Fix**: the route calls one service function; the service does everything:

```python
# CORRECT — route
@router.post("/{id}/messages", response_model=SessionOut)
async def send_message(id: uuid.UUID, body: MessageIn, user: Student, db: DB) -> SessionOut:
    try:
        return await svc.process_message(
            db=db, student_id=user.id, school_id=user.school_id,
            session_id=id, message=body,
        )
    except svc.StaleVersion:
        raise HTTPException(409, detail={"error": {"code": ErrorCode.CONFLICT, "message": "Stale session version"}})
    except svc.SessionNotFound:
        raise HTTPException(404, detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Session not found"}})
```

---

## Pattern: HTTPException raised in service

```python
# BAD — service raises HTTPException
from fastapi import HTTPException

def fail(detail, status=409):
    raise HTTPException(status_code=status, detail=detail)  # ← FastAPI in service

def apply_message(content, state, message):
    ...
    if state["complete"] and action != "help":
        fail("review_complete")                              # ← HTTPException from service
```

**Fix**: define domain exceptions in the service module:

```python
# CORRECT — in app/services/review.py
class ReviewComplete(Exception): pass
class StaleQuestion(Exception): pass
class InvalidOption(ValueError): pass

def apply_message(content, state, message):
    ...
    if state["complete"] and action != "help":
        raise ReviewComplete
```

The route catches and converts:

```python
except svc.ReviewComplete:
    raise HTTPException(409, detail={"error": {"code": "review_complete", "message": "Review already finished"}})
```

---

## Pattern: missing response_model

Every route must declare `response_model`. Without it FastAPI:
- Does not validate the output (a bug in the serializer goes unnoticed)
- Does not include the response schema in OpenAPI docs
- May leak fields that were supposed to be hidden (e.g. `answer`, `keywords`)

```python
# BAD
@router.get("/study-lessons")
async def lessons(user: Student, db: DB, locale: Locale = "en"):
    rows = ...
    return [lesson_public(row, locale) for row in rows]   # raw dict

# CORRECT
@router.get("/study-lessons", response_model=list[LessonOut])
async def lessons(user: Student, db: DB, locale: Locale = "en") -> list[LessonOut]:
    return await svc.list_lessons(db=db, locale=locale)
```

---

## Pattern: ORM object returned from service / leaked past commit

After `await db.commit()`, SQLAlchemy marks all attributes of the committed objects as expired. Accessing any attribute outside the async context triggers a lazy load, which in async SQLAlchemy raises `sqlalchemy.exc.MissingGreenlet`.

```python
# BAD
async def create_session(...) -> ReviewSession:
    session = ReviewSession(...)
    db.add(session)
    await db.commit()
    return session   # ← expired ORM object; caller accesses .id → MissingGreenlet

# CORRECT — return a Pydantic schema, not an ORM object
async def create_session(...) -> SessionOut:
    session = ReviewSession(...)
    db.add(session)
    await db.flush()
    await db.commit()
    await db.refresh(session)    # re-reads all columns from DB
    return SessionOut.model_validate(session)
```

For relationships loaded before commit:

```python
# Capture counts BEFORE flush — relationship is still in-memory
q_count = len(assignment.questions) if assignment.questions else 0
await db.flush()
await db.commit()
await db.refresh(assignment)
return AssignmentOut(question_count=q_count, ...)
```

---

## Post-commit refresh checklist

After any `await db.commit()`:
1. Call `await db.refresh(obj)` if you need any server-side column (`id`, `created_at`, `updated_at`, anything with `server_default` or `onupdate`).
2. Capture relationship sizes / objects **before** flush if you need them in the response.
3. Return a Pydantic schema built from the refreshed object, not the ORM object itself.

---

## school_id scoping checklist

Before writing any `select()`:

```python
# Is this a global catalog? (no user data, read-only, shared across all schools)
#   → school_id scoping not needed
# Is this student/teacher/session/assignment/submission data?
#   → school_id MUST be in the WHERE clause

select(ReviewSession).where(
    ReviewSession.id == session_id,
    ReviewSession.school_id == school_id,   # ← required
    ReviewSession.student_id == student_id, # ← required for student-owned resources
)
```

If you're unsure, add the `school_id` filter. The cost of an extra filter is zero; the cost of a PDPL breach is existential.

---

## Error shape — always use this

```python
raise HTTPException(
    status_code=404,
    detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Session not found"}},
)
```

Never:
```python
raise HTTPException(404, "session_not_found")      # bare string — breaks client parsers
raise HTTPException(detail="not found", status_code=404)  # missing error envelope
```

`ErrorCode` lives in `app/core/errors.py`. Add new codes there; never invent ad-hoc string literals in routes or services.

---

## Review this branch before merging

When reviewing code generated by an agent, check `app/api/routes/*.py` for:

1. Any `select(`, `db.execute(`, `db.get(`, `db.add(`, `db.commit(` → must be moved to services
2. Any `async def` helper that accepts `db` → helper must live in services
3. Any `raise HTTPException` in a service file → convert to domain exception
4. Any route missing `response_model=` → add the schema
5. Any `HTTPException(code, "bare_string")` → add error envelope
6. Any `select()` without `school_id` in WHERE on user-owned data → PDPL violation
