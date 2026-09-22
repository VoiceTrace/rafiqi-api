from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, homework, study_sessions, users
from app.core.config import settings

description = """
## Rafiqi API

Backend for **Rafiqi** — an AI-powered education platform for teachers and students,
built for the Saudi Arabian (KSA) market.

### Authentication

All protected endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Obtain a token pair by calling **POST /auth/login**. Access tokens are short-lived —
exchange the accompanying `refresh_token` for a new pair via **POST /auth/refresh**
rather than logging in again. Call **POST /auth/logout** to revoke a refresh token.

### Multi-tenancy

Every response is automatically scoped to the requesting user's school.
A user from School A will never see data from School B — this is enforced
server-side and cannot be bypassed by the client.

### Roles

| Role | Description |
|---|---|
| `teacher` | Can view class rosters, generate lesson plans, run live sessions |
| `student` | Can chat with Rafiqi, view their own profile, join live sessions |

Routes are role-protected — sending a teacher token to a student-only route
returns `403 Forbidden`.

### Error shape

All errors follow a consistent shape:

```json
{
  "detail": {
    "error": {
      "code": "unauthorized",
      "message": "Invalid or expired token"
    }
  }
}
```

Known error codes: `unauthorized`, `forbidden`, `not_found`, `validation_error`, `internal_error`.
"""

tags_metadata = [
    {
        "name": "auth",
        "description": "Login and obtain a JWT access token.",
    },
    {
        "name": "users",
        "description": "User management — CRUD for teachers and students within a school. "
                       "`GET /users/me` and `PATCH /users/me` are available to both roles. "
                       "All other routes are teacher-only.",
    },
    {
        "name": "profiles",
        "description": "Student profile — traits, confidence scores, teaching tips. "
                       "Built automatically from Cave chat (A2/A3). "
                       "Teachers read; students see their own.",
    },
    {
        "name": "conversations",
        "description": "Cave chat sessions between a student and Rafiqi (A2). "
                       "Each session produces profile trait updates (A3).",
    },
    {
        "name": "lessons",
        "description": "Lesson prep — objectives, flow, check-questions (B1/B2/B3).",
    },
    {
        "name": "study-sessions",
        "description": "Epic D — Student study sessions with Rafiqi. "
                       "State machine: setup → review → check_in → deepen → wrap_up → closed. "
                       "Generates questions, captures attempts, scores with hint ladder, "
                       "computes mastery records on close.",
    },
    {
        "name": "homework",
        "description": "Epic E — Homework assignments. "
                       "Teachers create MCQ assignments, add questions, and bulk-distribute to students. "
                       "Students retrieve their assignments (no correct answers until submitted) and submit answers. "
                       "Submission reveals correct answers and writes mastery records. "
                       "Gap-digest endpoint aggregates class-level concept weaknesses for the teacher.",
    },
    {
        "name": "sessions",
        "description": "Live class sessions — start, join, real-time sync (C1/C2).",
    },
    {
        "name": "health",
        "description": "Service health check.",
    },
]

# Ensure upload directories exist before StaticFiles mounts
Path(settings.MEDIA_DIR, "avatars").mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Rafiqi API",
    version="0.1.0",
    description=description,
    openapi_tags=tags_metadata,
    contact={
        "name": "EntraI Engineering",
        "email": "eng@entrai.com",
    },
    license_info={
        "name": "Private — EntraI",
    },
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(study_sessions.router)
app.include_router(homework.router)

app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")


@app.get("/health", tags=["health"], summary="Health check")
async def health():
    """Returns `ok` when the service is running. No auth required."""
    return {"status": "ok"}
