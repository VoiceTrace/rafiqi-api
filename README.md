# Rafiqi API

Backend for Rafiqi — an education app for teachers and students, built for the Saudi Arabian (KSA) market.

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI (async) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2 (async) |
| Migrations | Alembic |
| Auth | JWT (python-jose + bcrypt), 6h expiry |
| Testing | pytest + pytest-asyncio + httpx |

## Prerequisites

- Python 3.12+
- Docker (for local PostgreSQL)

## Local Setup

**1. Clone and create a virtual environment**

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Start the database**

```bash
docker compose up -d
```

This starts PostgreSQL 16 on port 5432 with a named volume so data persists across restarts. To stop: `docker compose down`. To wipe data too: `docker compose down -v`.

**4. Configure environment**

```bash
cp .env.example .env
# Edit .env if your DB credentials differ from the defaults
```

**5. Run migrations**

```bash
alembic upgrade head
```

**6. Seed development data**

```bash
python scripts/seed.py
```

Creates one school, one teacher, and one student:

| Role | Email | Password |
|---|---|---|
| Teacher | teacher@alnoor.edu.sa | teacher123 |
| Student | student@alnoor.edu.sa | student123 |

**7. Start the server**

```bash
uvicorn app.main:app --reload --port 8000
```

API is available at `http://localhost:8000`.

## API Docs

| URL | Tool | Use for |
|---|---|---|
| `http://localhost:8000/docs` | Swagger UI | Interactive testing — try requests directly in the browser |
| `http://localhost:8000/redoc` | ReDoc | Readable reference — cleaner layout for reading the full spec |
| `http://localhost:8000/openapi.json` | Raw OpenAPI schema | Import into Postman, Insomnia, or generate a client SDK |

The docs include example request bodies (teacher + student credentials pre-filled), JWT token format, error shapes, and role/multi-tenancy explanations. No backend knowledge required to use the API from the frontend.

## Running Tests

```bash
pytest
```

All tests run without a database connection — models, schemas, auth logic, and confidence threshold are tested at the unit level.

## Project Structure

```
app/
  api/
    routes/       # One file per resource (auth.py, profiles.py, ...)
    deps.py       # Shared FastAPI dependencies (auth, DB session)
  models/         # SQLAlchemy ORM models
  schemas/        # Pydantic request/response schemas
  services/       # Business logic — routes stay thin
  core/
    config.py     # Settings (reads .env)
    database.py   # Async engine + session factory
    security.py   # Password hashing + JWT
    errors.py     # Error code enum
  main.py
alembic/
  versions/       # Migration files (named by ticket ID)
scripts/
  seed.py         # Dev seed data
tests/
.claude/
  CLAUDE.md       # Project context and decisions for Claude Code
  STATUS.md       # Build progress tracker
```

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Health check |
| POST | `/auth/login` | None | Login — returns JWT |

More endpoints added per ticket. See `.claude/STATUS.md` for current build progress.

## Auth

All protected routes require a `Bearer` token in the `Authorization` header:

```
Authorization: Bearer <token>
```

The JWT payload carries `sub` (user ID), `school_id`, `role`, and `exp`. Tokens expire after 6 hours.

## Multi-tenancy

Every table holding student, teacher, or school data has a `school_id` column. All queries are scoped to the requesting user's school — this is enforced at the service layer and tested explicitly. Required by PDPL (Saudi Personal Data Protection Law).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async DB URL (app) |
| `DATABASE_URL_SYNC` | `postgresql+psycopg2://...` | Sync DB URL (Alembic) |
| `SECRET_KEY` | `change-me-in-production` | JWT signing key |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_HOURS` | `6` | Token lifetime |
| `ENVIRONMENT` | `development` | `development` or `production` |
