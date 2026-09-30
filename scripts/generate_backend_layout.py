"""Generate source-based architecture/schema documentation without connecting to a DB."""
from pathlib import Path
from datetime import date
import ast
import json
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, CreateIndex
from app.core.database import Base
import app.models  # registers metadata; no database connection

OUT = ROOT / "docs" / "backend-layout"
OUT.mkdir(parents=True, exist_ok=True)
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
dialect = postgresql.dialect()

# Reconstruct final DDL from declarative migration operations. Data migrations are
# intentionally not executed: no credentials, network, or database is required.
revisions = {}
for path in (ROOT / "alembic/versions").glob("*.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                values[target.id] = ast.literal_eval(node.value)
    revisions[values["revision"]] = (values["down_revision"], path, tree)
chain = []
previous = None
while len(chain) < len(revisions):
    matches = [key for key, value in revisions.items() if value[0] == previous]
    if len(matches) != 1:
        raise RuntimeError("Expected a single linear migration chain")
    previous = matches[0]
    chain.append(previous)

metadata = sa.MetaData()
env = {"sa": sa, "postgresql": postgresql, "op": SimpleNamespace(f=lambda name: name)}
def evaluate(node):
    return eval(compile(ast.Expression(node), "<migration-ddl>", "eval"), {"__builtins__": {}}, env)

operations = {"create_table", "add_column", "alter_column", "create_foreign_key", "create_index"}
for revision in chain:
    upgrade = next(n for n in revisions[revision][2].body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    calls = sorted((n for n in ast.walk(upgrade) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "op" and n.func.attr in operations), key=lambda n: n.lineno)
    for call in calls:
        args = [evaluate(n) for n in call.args]
        kwargs = {n.arg: evaluate(n.value) for n in call.keywords}
        action = call.func.attr
        if action == "create_table":
            sa.Table(args[0], metadata, *args[1:], **kwargs)
        elif action == "add_column":
            metadata.tables[args[0]].append_column(args[1])
        elif action == "alter_column":
            if set(kwargs) != {"nullable"}:
                raise RuntimeError("Unhandled alteration")
            metadata.tables[args[0]].c[args[1]].nullable = kwargs["nullable"]
        elif action == "create_foreign_key":
            name, source, target, local, remote = args
            metadata.tables[source].append_constraint(sa.ForeignKeyConstraint(local, [f"{target}.{c}" for c in remote], name=name, **kwargs))
        elif action == "create_index":
            name, table, columns = args
            sa.Index(name, *[metadata.tables[table].c[c] for c in columns], **kwargs)

assert set(metadata.tables) == set(Base.metadata.tables)
for table in metadata.tables.values():
    model = Base.metadata.tables[table.name]
    assert set(table.c.keys()) == set(model.c.keys()), table.name
    for column in table.c:
        assert column.nullable == model.c[column.name].nullable, (table.name, column.name)
        assert str(column.type.compile(dialect=dialect)) == str(model.c[column.name].type.compile(dialect=dialect))
    fks = lambda t: {(f.parent.name, f.target_fullname, f.ondelete) for f in t.foreign_keys}
    assert fks(table) == fks(model), table.name
    uniques = lambda t: {tuple(c.columns.keys()) for c in t.constraints if isinstance(c, sa.UniqueConstraint)}
    assert uniques(table) == uniques(model), table.name
    indexes = lambda t: {(i.name, tuple(i.columns.keys()), i.unique) for i in t.indexes}
    assert indexes(table) == indexes(model), table.name
    checks = lambda t: {(c.name, str(c.sqltext)) for c in t.constraints if isinstance(c, sa.CheckConstraint)}
    assert checks(table) == checks(model), table.name

purposes = {
    "schools": "Tenant root: school identity.",
    "users": "Teachers and students share one table; email is globally unique. Deactivation sets is_active=false.",
    "student_profiles": "Optional one-to-one profile anchor for a user; no dedicated profile endpoint is currently mounted.",
    "profile_traits": "Profile preferences/goals, confidence and optional conversation provenance; no mounted trait API.",
    "conversations": "Lightweight Cave-session scaffold. Does not store messages and has no mounted conversation API.",
    "refresh_tokens": "Hashed refresh-token credentials, expiry and revocation; tenant ownership is indirect through users.",
    "review_subjects": "Global bilingual subject catalog, shared across schools.",
    "review_chapters": "Global bilingual chapters belonging to subjects.",
    "review_lessons": "Global lessons with bilingual JSON content, concepts, questions and private rubrics.",
    "review_sessions": "One persistent review per school/student/lesson; lesson snapshot and conversation state are JSON.",
    "review_attempts": "Persisted answer evidence, assessment score, assistance and error taxonomy.",
    "mastery_records": "Recomputable concept mastery by school, student and subject.",
    "review_session_summaries": "One immutable application-level completion snapshot per session; localized at read time.",
}

def write(name, content):
    (OUT / name).write_text("\n".join(line.rstrip() for line in content.rstrip().splitlines()) + "\n", encoding="utf-8")

erd = ["erDiagram"]
dictionary = ["# Database layout", "", f"Source commit: `{commit}`. Migration head: `{chain[-1]}`.", "",
              "This is the schema reconstructed from committed migration DDL, cross-checked against ORM metadata. It is not a live database inspection.", "",
              "PK = primary key; FK = foreign key; UK = individually unique. Composite uniqueness is listed separately. All timestamps are timezone-aware. FLOAT is PostgreSQL double precision unless a precision is specified.", ""]
schema_json = {"commit": commit, "migration_head": chain[-1], "tables": []}
sql = [f"-- Rafiqi schema at {commit}", f"-- Migration head: {chain[-1]}",
       "-- Reconstructed application DDL only; no seed data or alembic_version state.",
       "-- Use Alembic migrations for deployment; this file is a database-layout reference.", ""]
for table in metadata.sorted_tables:
    single_unique = {tuple(c.columns.keys())[0] for c in table.constraints if isinstance(c, sa.UniqueConstraint) and len(c.columns) == 1}
    single_unique |= {tuple(i.columns.keys())[0] for i in table.indexes if i.unique and len(i.columns) == 1}
    erd.append(f"    {table.name} {{")
    dictionary += [f"## {table.name}", "", purposes[table.name], "", "| Column | PostgreSQL type | Nullable | Keys | Database default | ORM insert default |", "|---|---|---|---|---|---|"]
    record = {"name": table.name, "purpose": purposes[table.name], "columns": [], "constraints": [], "indexes": []}
    for c in table.c:
        typ = str(c.type.compile(dialect=dialect))
        keys = (["PK"] if c.primary_key else []) + (["FK"] if c.foreign_keys else []) + (["UK"] if c.name in single_unique else [])
        db_default = str(c.server_default.arg) if c.server_default is not None else "—"
        orm = Base.metadata.tables[table.name].c[c.name]
        orm_default = "—" if orm.default is None else (getattr(orm.default.arg, "__name__", "callable") + "()" if callable(orm.default.arg) else str(orm.default.arg))
        er_type = typ.lower().replace(" ", "_")
        erd.append(f'        {er_type} {c.name}' + (" " + ",".join(keys) if keys else "") + f' "{"nullable" if c.nullable else "required"}"')
        dictionary.append(f"| `{c.name}` | `{typ}` | {'yes' if c.nullable else 'no'} | {', '.join(keys) or '—'} | `{db_default}` | `{orm_default}` |")
        record["columns"].append({"name": c.name, "type": typ, "nullable": c.nullable, "keys": keys, "database_default": None if db_default == "—" else db_default, "orm_default": None if orm_default == "—" else orm_default})
    erd.append("    }")
    dictionary += ["", "Constraints and indexes:", ""]
    for con in sorted(table.constraints, key=lambda c: (type(c).__name__, str(c.name), str(c))):
        name = str(con.name or "unnamed")
        if isinstance(con, sa.ForeignKeyConstraint):
            detail = f"FK ({', '.join(con.columns.keys())}) → {', '.join(e.target_fullname for e in con.elements)}; ON DELETE {con.ondelete or 'NO ACTION'}"
        elif isinstance(con, sa.CheckConstraint):
            detail = f"CHECK {con.sqltext}"
        else:
            detail = f"{'PRIMARY KEY' if isinstance(con, sa.PrimaryKeyConstraint) else 'UNIQUE'} ({', '.join(con.columns.keys())})"
        dictionary.append(f"- `{name}`: {detail}.")
        record["constraints"].append({"name": name, "definition": detail})
    for idx in sorted(table.indexes, key=lambda i: i.name):
        detail = f"{'UNIQUE ' if idx.unique else ''}INDEX ({', '.join(idx.columns.keys())})"
        dictionary.append(f"- `{idx.name}`: {detail}.")
        record["indexes"].append({"name": idx.name, "definition": detail})
    dictionary.append("")
    schema_json["tables"].append(record)
    sql.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
    sql.extend(str(CreateIndex(idx).compile(dialect=dialect)) + ";" for idx in sorted(table.indexes, key=lambda i: i.name))
    sql.append("")
    for fk in sorted(table.foreign_keys, key=lambda f: f.parent.name):
        parent = fk.column.table.name
        parent_end = "|o" if fk.parent.nullable else "||"
        child_end = "o|" if fk.parent.name in single_unique else "o{"
        erd.append(f'    {parent} {parent_end}..{child_end} {table.name} : "{fk.parent.name}"')

write("database-erd.mmd", "\n".join(erd))
write("database-schema.sql", "\n".join(sql))
write("database-schema.json", json.dumps(schema_json, ensure_ascii=False, indent=2))
write("database-layout.md", "\n".join(dictionary))

# Enumerate route definitions from actual source, not potentially stale OpenAPI.
api = ["# Implemented API", "", "The following routes are mounted by app/main.py. /docs, /redoc, /openapi.json and the /media static mount are additional framework surfaces.", "", "| Method | Path | Access | Handler | Service calls |", "|---|---|---|---|---|"]
route_count = 0
for path in sorted((ROOT / "app/api/routes").glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefix = ""
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == "APIRouter":
            prefix = next((ast.literal_eval(k.value) for k in n.value.keywords if k.arg == "prefix"), "")
    for fn in tree.body:
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for dec in fn.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute) or not isinstance(dec.func.value, ast.Name) or dec.func.value.id != "router":
                continue
            source = ast.unparse(fn.args)
            access = "student" if path.stem == "review" else "teacher" if "require_teacher" in source else "authenticated" if "get_current_user" in source else "public; credentials/token in body"
            calls = sorted({ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in {"svc", "catalog", "auth_svc", "user_svc"}})
            api.append(f"| {dec.func.attr.upper()} | `{prefix + ast.literal_eval(dec.args[0])}` | {access} | `{path.name}:{fn.name}` | {', '.join(f'`{c}`' for c in calls)} |")
            route_count += 1
api.append("| GET | `/health` | public | `main.py:health` | none; process health only |")
route_count += 1
write("api-layout.md", "\n".join(api))

architecture = '''flowchart TB
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
'''
write("backend-architecture.mmd", architecture)
auth_flow = '''sequenceDiagram
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
    Service->>DB: Revoke token if still active; commit when changed
    API-->>Client: 204
    Note over Client,Service: Already-issued access JWT remains valid until expiry
'''
write("authentication-flow.mmd", auth_flow.replace(";", ","))
review_flow = '''sequenceDiagram
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
        Service->>DB: Read lesson; insert content snapshot and initial state; commit
        Service-->>Student: New session (201)
    end
    Student->>API: POST messages (request_id, expected_version, action, locale)
    API->>Service: process_message
    Service->>DB: SELECT owned session FOR UPDATE
    alt Request ID already in recent history
        Service-->>Student: Current session; no mutation
    else Version mismatch
        Service-->>Student: 409 stale_session
    else Valid request
        Note over Service: Validate action and question; apply deterministic state transition
        opt Action produces an answer
            Service->>DB: Insert attempt; flush
            Service->>DB: Read concept evidence; upsert mastery
        end
        opt Transition to complete
            Service->>DB: Recalculate concept mastery and insert one completion summary
        end
        Service->>DB: Commit state, version and evidence together; refresh session
        Service-->>Student: Safe localized session projection and optional summary
    end
'''
write("review-flow.mmd", review_flow.replace(";", ","))
state = '''stateDiagram-v2
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
'''
write("review-state.mmd", state)
migration_lines = ["flowchart LR"]
for i, revision in enumerate(chain):
    migration_lines.append(f'    m{i}["{revision}<br/>{revisions[revision][1].stem.split("_", 1)[1]}"]')
    if i:
        migration_lines.append(f"    m{i-1} --> m{i}")
write("migration-history.mmd", "\n".join(migration_lines))

json_notes = '''# JSON storage and application semantics

These columns use PostgreSQL `JSON`, not `JSONB`. The database has no JSON-schema validation, JSON-path indexes, question table, concept table, or foreign keys for references inside JSON.

| Column | Stored structure |
|---|---|
| review_subjects.title / review_chapters.title | Object with `en` and `ar` localized strings. |
| review_lessons.content | `subject_id`, `chapter_id`, and localized `en`/`ar` objects containing `title`, `subject`, `chapter`, `objective`, `key_points`, `concept_refs`, `questions`. |
| review_sessions.content | Snapshot of lesson content taken at creation; later lesson edits do not automatically replace existing snapshots. The catalog migration enriches old snapshots with metadata. |
| review_sessions.state | `index`, `attempts`, `hint_level`, `assistance`, `resolved`, `complete`, `events`, `requests`. |
| review_session_summaries.concepts | Array of objects with `concept_ref`, `mastery_band`, `completed_with_support`, `dominant_error_type`. |

Each concept descriptor has `id`, `title`, `description`. Questions contain `id`, `kind` (`choice` or `written`), `text`, `options`, `concept_ref`, `hints`, `explanation` and scoring fields (`answer` for choices, `keywords` for written questions). Options have `id` and `text`. Private scoring fields are excluded from the public question projection.

Transcript event kinds are `text`, `question`, `answer`, `feedback`, `hint`, `action`, and `complete`. Fields vary by kind: role, text/copy, locale, question ID/index, concept reference, score, attempt, hint level, assistance and action. Events are embedded in state; they are not separate message rows. The service rejects processing when the existing event count is at least 1,000; one action may append multiple events. Recent request history keeps 200 IDs. Answer attempts additionally have a persistent `(session_id, request_id)` unique constraint.

Mastery uses the latest attempt per `(lesson_id, question_id)` for a student's subject/concept. Its score is the arithmetic mean of those evidence scores: below 0.5 = `needs_support`, below 0.8 = `developing`, otherwise `secure`. Attempt count includes all attempts; evidence count includes latest-per-question evidence. Assistance is counted separately and does not reduce the score. `dominant_error_type` is the most recent non-null error among current evidence, not the most frequent error. The calculation version is `mvp-v1`.

Completion summaries are immutable by service behavior, not by a database trigger. A summary captures current concept mastery (which can include other lessons), total attempts in this session, and whether its latest evidence used support. Response copy is localized from the snapshot at read time. Historical completed sessions can lack a summary; reads do not backfill one.

Tenant-owned rows reference schools/users independently. The schema has no composite foreign keys enforcing that a referenced student/session belongs to the row's school, and the migrations define no row-level-security policies. Review services scope owned records by both school and student. Catalog tables are global. Refresh-token ownership is indirect via the user. Authentication uses JWT claims; its dependency does not reload account status on every protected request.

Roles, trait category/confidence, locale, question IDs, concept references and some numeric ranges are application conventions unless an explicit CHECK appears in the database reference. A student_id FK points to users and does not itself require the student role. A user can have zero or one student profile. Profile traits have no unique constraint on `(profile_id, trait_key)`.

UUIDs are generated by the application (`uuid4`), with no database UUID default. ORM `onupdate=now()` is not a PostgreSQL update trigger. Migrations add database defaults for `profile_traits.score=0.0`, `profile_traits.confidence='still_forming'`, and `review_sessions.version=0`; the ORM expresses these as client defaults. The schema SQL preserves the migration defaults.

The current review engine is deterministic demo logic (`mock: true`), with no external LLM call. Conversation and profile tables are scaffolding; only auth, users and review routers are mounted. Descriptive OpenAPI tags mentioning lesson planning or live sessions do not imply implemented endpoints.
'''
write("json-and-behavior.md", json_notes)

readme = ["# Rafiqi backend: architecture and database", "", f"Generated from source commit `{commit}` on {date.today().isoformat()} (initial baseline: latest `main`).", "",
          f"Scope: **{len(metadata.tables)} application tables, {sum(len(t.c) for t in metadata.tables.values())} columns, {sum(len(t.foreign_keys) for t in metadata.tables.values())} foreign keys, {route_count} API operations, {len(chain)} migrations**. PostgreSQL 16 is the local Compose target.", "",
          "## Files", "", "- [Complete architecture assessment](architecture-review.md)", "- [Rendered diagrams](rendered/README.md)", "- [Complete database dictionary](database-layout.md)", "- [PostgreSQL schema SQL](database-schema.sql)", "- [Machine-readable schema](database-schema.json)", "- [Implemented API inventory](api-layout.md)", "- [JSON structures and behavior](json-and-behavior.md)", "",
          "## Evidence and boundaries", "", "The schema was reconstructed from migration declarations without running their data operations, then checked against SQLAlchemy models for tables, columns, types, nullability, foreign keys, unique constraints, checks and indexes. SQL is reference DDL; deploy with Alembic so catalog seed data and version history are applied. The Alembic-owned `alembic_version` bookkeeping table is not one of the 13 application tables. No live database was inspected or modified.", "",
          "The checked-in generator can refresh these files with the backend Python environment: `python scripts/generate_backend_layout.py`. Diagrams describe implemented behavior, rather than future product-plan features. Each diagram is also supplied as editable `.mmd` source.", ""]
for title, name in [("Backend architecture", "backend-architecture.mmd"), ("Complete entity relationship diagram", "database-erd.mmd"), ("Authentication", "authentication-flow.mmd"), ("Review persistence flow", "review-flow.mmd"), ("Review state transitions", "review-state.mmd"), ("Migration history", "migration-history.mmd")]:
    readme += [f"## {title}", "", f"[Mermaid source]({name})", "", "```mermaid", (OUT / name).read_text(encoding="utf-8").rstrip(), "```", ""]
write("README.md", "\n".join(readme))
print(json.dumps({"tables": len(metadata.tables), "columns": sum(len(t.c) for t in metadata.tables.values()), "foreign_keys": sum(len(t.foreign_keys) for t in metadata.tables.values()), "api_operations": route_count, "migrations": len(chain), "head": chain[-1], "output": str(OUT)}))
