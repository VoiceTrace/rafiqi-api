# Rafiqi API — Agent Instructions

Read this file before writing any code. It defines the architecture rules for this codebase. Violating these rules will cause review failure.

---

## Layer rules — the most important section

This project has three strict layers. Each layer has exactly one job.

```
HTTP request
    ↓
Route function   (app/api/routes/*.py)
    ↓
Service function (app/services/*.py)
    ↓
Database         (SQLAlchemy async session)
```

### Routes are thin. They do exactly three things:

1. Parse input (Pydantic handles this automatically).
2. Call **one** service function.
3. Return the result.

**Routes must not contain:**
- `select()`, `db.execute()`, `db.get()`, `db.add()`, `db.delete()`, `db.commit()`, `db.flush()`, `db.refresh()` — any SQLAlchemy operation.
- Business logic (branching on model state, computing scores, building event lists).
- Helper functions that do database work (`async def owned(...)` in a route file is a violation).

If you find yourself writing a database query in a route function, stop. Move it to a service.

### Services own all database access. They:

- Accept a `db: AsyncSession` as their first positional argument (after `self` if a class method, but prefer module-level functions).
- Run all queries, commits, rollbacks, and refreshes.
- Return **Pydantic schema instances** or plain Python values — never ORM objects (SQLAlchemy models must not leak out of the service layer).
- Raise **domain exceptions**, not `HTTPException`. The route catches domain exceptions and converts them to HTTP responses.

**Services must not import from `fastapi`.**

### Database session lifecycle

The session is provided by `app/api/deps.get_db_session`, which yields a session and closes it on exit. It does **not** commit automatically — every write path must call `await db.commit()` explicitly.

Post-commit pattern for server-side columns (e.g. `updated_at` with `onupdate=func.now()`):

```python
# Capture relationship counts BEFORE flush (lazy load after commit raises MissingGreenlet)
count = len(obj.related) if obj.related else 0
await db.flush()
await db.commit()
await db.refresh(obj)          # re-reads server-side columns
return MySchema(count=count, ...)
```

---

## File layout

```
app/
  api/
    routes/      # one file per resource — THIN only
    deps.py      # shared FastAPI dependencies (auth, db session)
  models/        # SQLAlchemy ORM models (tables)
  schemas/       # Pydantic request/response models
  services/      # all business logic + all DB access
  core/
    config.py
    database.py
    errors.py    # ErrorCode enum — use this, never invent string literals
    security.py
  main.py
alembic/
tests/
```

---

## Route skeleton

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentUser, get_db_session, require_student
from app.schemas.foo import FooOut, FooCreate
from app.services import foo as svc

router = APIRouter(prefix="/foo", tags=["foo"])
Student = Annotated[CurrentUser, Depends(require_student)]
DB = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("", response_model=FooOut, status_code=201)
async def create_foo(body: FooCreate, user: Student, db: DB) -> FooOut:
    return await svc.create_foo(db=db, school_id=user.school_id, user_id=user.id, req=body)
```

Rules visible in this skeleton:
- `response_model` is always declared.
- The route calls exactly one service function and returns its result.
- `school_id` is always passed from `user.school_id` — never trusted from the request body.
- Auth dependency is declared on the function signature, not checked inside the body.

---

## Service skeleton

```python
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.foo import Foo
from app.schemas.foo import FooOut, FooCreate
from app.core.errors import ErrorCode


class FooNotFound(Exception):
    pass


async def create_foo(db: AsyncSession, school_id: uuid.UUID, user_id: uuid.UUID, req: FooCreate) -> FooOut:
    row = Foo(school_id=school_id, created_by=user_id, title=req.title)
    db.add(row)
    await db.flush()
    await db.commit()
    await db.refresh(row)
    return FooOut.model_validate(row)


async def get_foo(db: AsyncSession, school_id: uuid.UUID, foo_id: uuid.UUID) -> FooOut:
    row = await db.scalar(
        select(Foo).where(Foo.id == foo_id, Foo.school_id == school_id)
    )
    if row is None:
        raise FooNotFound(foo_id)
    return FooOut.model_validate(row)
```

Rules visible in this skeleton:
- No FastAPI import.
- Domain exception (`FooNotFound`), not `HTTPException`.
- Every query is scoped to `school_id` (PDPL hard rule).
- Returns a Pydantic schema, not an ORM object.

---

## Route: catching domain exceptions

```python
from app.services.foo import FooNotFound
from app.core.errors import ErrorCode

@router.get("/{foo_id}", response_model=FooOut)
async def get_foo(foo_id: uuid.UUID, user: Student, db: DB) -> FooOut:
    try:
        return await svc.get_foo(db=db, school_id=user.school_id, foo_id=foo_id)
    except FooNotFound:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Not found"}},
        )
```

---

## Error shape

Every `HTTPException` must use this `detail` structure — never a bare string:

```python
# CORRECT
raise HTTPException(
    status_code=404,
    detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Resource not found"}},
)

# WRONG — bare string
raise HTTPException(404, "not_found")
```

`ErrorCode` lives in `app/core/errors.py`. Use existing codes; add new ones to that enum rather than inventing string literals.

---

## Multi-tenancy (PDPL hard rule)

Every query that touches student, teacher, school, or any user-owned data **must** be scoped to `school_id`. This is non-negotiable under Saudi PDPL.

```python
# CORRECT — scoped
select(Foo).where(Foo.id == foo_id, Foo.school_id == school_id)

# WRONG — unscoped, PDPL violation
select(Foo).where(Foo.id == foo_id)
```

If you write a query and `school_id` is not in the `WHERE` clause, stop and ask whether it should be. The only safe exceptions are read-only global catalog tables (`review_lessons`, for example) that contain no user data.

---

## Auth

Auth is enforced via FastAPI dependencies in `app/api/deps.py`:

- `require_teacher` → 403 if role is not `teacher`
- `require_student` → 403 if role is not `student`
- `get_current_user` → authenticated, any role

Declare the dependency on the route function signature. Never check `user.role` manually inside a route body.

---

## Pydantic schemas

- One file per resource in `app/schemas/`.
- Never expose a SQLAlchemy model directly as a response schema — always use a Pydantic model.
- Use `model_validate(orm_obj)` with `model_config = ConfigDict(from_attributes=True)` to convert ORM → schema.
- The response schema is the contract. If a field shouldn't reach the client (e.g. `answer`, `keywords`, `hints` beyond the revealed level), it must not appear in the schema.

---

## Async

All route functions and service functions are `async def`. All SQLAlchemy calls use `await`. Do not use synchronous SQLAlchemy in async context — it will deadlock under load.

---

## CORS

`app/main.py` must register `CORSMiddleware` before any router. The frontend at `http://localhost:3000` must be in `allow_origins`. Middleware must be added with `app.add_middleware(...)` before `app.include_router(...)`.

---

## Checklist before marking any route done

- [ ] Route function has `response_model=...`.
- [ ] Route function body contains zero SQLAlchemy calls.
- [ ] Route function body calls exactly one service function.
- [ ] Service function scopes every query to `school_id` (unless the table is a global catalog with no user data).
- [ ] Service function contains no FastAPI imports, no `HTTPException`.
- [ ] Any `HTTPException` raised in route uses the structured `detail` shape, not a bare string.
- [ ] Error codes come from `ErrorCode` enum in `app/core/errors.py`.
- [ ] Auth dependency is declared on the function signature.
