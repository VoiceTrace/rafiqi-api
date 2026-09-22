"""Mock behavior plus opt-in real PostgreSQL API tests (dedicated review test DB)."""
import asyncio
import json
import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api.deps import CurrentUser, require_student, get_db_session
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import School, User
from app.models.review import ReviewLesson, ReviewSession
from app.schemas.review import ReviewMessage
from app.services.review import apply_message, initial_state, session_public
from app.services.review_seed import LESSON


def command(action, version=0, question="force-pairs", **kwargs):
    return dict(request_id=str(uuid.uuid4()), expected_version=version, action=action,
                question_id=question, locale="en", **kwargs)


def test_hints_help_and_attempts_are_independent():
    state = initial_state()
    for level in range(1, 4):
        state = apply_message(LESSON, state, ReviewMessage(**command("hint")))
        assert state["hint_level"] == level
        assert state["attempts"] == 0
    state = apply_message(LESSON, state, ReviewMessage(**command("chat", text="Why do they not cancel?")))
    assert state["attempts"] == 0
    state = apply_message(LESSON, state, ReviewMessage(**command("answer", option_id="equal")))
    attempt = next(e for e in reversed(state["events"]) if e["kind"] == "answer")
    assert attempt["hint_level"] == 3 and attempt["assisted"]
    assert state["attempts"] == 1 and state["resolved"]


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_complete_written_flow_and_no_key_leak(locale):
    state = initial_state()
    state = apply_message(LESSON, state, ReviewMessage(**command("answer", option_id="equal")))
    state = apply_message(LESSON, state, ReviewMessage(**command("next")))
    args = command("chat", question="different-objects", text="different objects" if locale == "en" else "جسمين مختلفين")
    args["locale"] = locale
    state = apply_message(LESSON, state, ReviewMessage(**args))
    assert state["resolved"]
    state = apply_message(LESSON, state, ReviewMessage(**command("next", question="different-objects")))
    assert state["complete"]
    fake = SimpleNamespace(id=uuid.uuid4(), lesson_id="newton-third-law", content=LESSON, state=state, version=4)
    output = json.dumps(session_public(fake, locale))
    assert '"keywords"' not in output and '"answer":' not in output and '"hints"' not in output
    assert len(session_public(fake, locale)["questions"]) == 2


def test_invalid_and_stale_actions_do_not_mutate():
    state = initial_state()
    for args in [command("next"), command("answer", option_id="bad"), command("hint", question="wrong")]:
        with pytest.raises(HTTPException):
            apply_message(LESSON, state, ReviewMessage(**args))
    assert state == initial_state()
    for _ in range(3):
        state = apply_message(LESSON, state, ReviewMessage(**command("answer", option_id="none")))
    assert state["resolved"]
    assert LESSON["en"]["questions"][0]["explanation"] in state["events"][-1]["text"]
    with pytest.raises(HTTPException):
        apply_message(LESSON, state, ReviewMessage(**command("answer", option_id="equal")))


@pytest.mark.asyncio
async def test_role_gate_without_dependency_override():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/study-lessons")).status_code in (401, 403)
        token = create_access_token(uuid.uuid4(), uuid.uuid4(), "teacher")
        assert (await client.get("/study-lessons", headers={"Authorization": f"Bearer {token}"})).status_code == 403


@pytest_asyncio.fixture
async def api():
    url = os.environ.get("REVIEW_TEST_DATABASE_URL", "")
    if not url.endswith("/rafiqi_review_test"):
        pytest.skip("Set REVIEW_TEST_DATABASE_URL to a dedicated /rafiqi_review_test database")
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    school_id, student_id, other_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with factory() as db:
        db.add(School(id=school_id, name="Review test"))
        await db.flush()
        for uid in (student_id, other_id):
            db.add(User(id=uid, school_id=school_id, email=f"{uid}@example.test", full_name="Student", role="student", hashed_password="test"))
        db.add(ReviewLesson(id="newton-third-law", content=LESSON))
        await db.commit()
    identity = {"user": CurrentUser(student_id, school_id, "student")}
    async def user(): return identity["user"]
    async def database():
        async with factory() as db: yield db
    app.dependency_overrides[require_student] = user
    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, identity, other_id, factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_api_resume_idempotency_scope_and_completion(api):
    client, identity, other_id, factory = api
    created = await client.post("/study-sessions", json={"lesson_id": "newton-third-law"})
    assert created.status_code == 201
    session = created.json()
    sid = session["id"]
    again = await client.post("/study-sessions", json={"lesson_id": "newton-third-law"})
    assert again.status_code == 200 and again.json()["id"] == sid
    assert (await client.get("/study-sessions/by-lesson/newton-third-law")).json()["id"] == sid
    first = command("answer", option_id="equal")
    sent = await client.post(f"/study-sessions/{sid}/messages", json=first)
    assert sent.status_code == 200
    duplicate = await client.post(f"/study-sessions/{sid}/messages", json=first)
    assert duplicate.json()["version"] == 1
    assert duplicate.json()["attempts"] == 1
    stale = await client.post(f"/study-sessions/{sid}/messages", json=command("hint"))
    assert stale.status_code == 409
    for payload in [command("next", 1), command("chat", 2, "different-objects", text="different objects"), command("next", 3, "different-objects")]:
        result = await client.post(f"/study-sessions/{sid}/messages", json=payload)
        assert result.status_code == 200, result.text
    resumed = (await client.get(f"/study-sessions/{sid}")).json()
    assert resumed["complete"] and resumed["version"] == 4
    assert sum(e["kind"] == "answer" for e in resumed["messages"]) == 2
    identity["user"] = CurrentUser(other_id, identity["user"].school_id, "student")
    assert (await client.get(f"/study-sessions/{sid}")).status_code == 404
    assert (await client.post(f"/study-sessions/{sid}/messages", json=first)).status_code == 404
    assert (await client.get("/study-sessions/by-lesson/newton-third-law")).status_code == 404
    other = await client.post("/study-sessions", json={"lesson_id": "newton-third-law"})
    assert other.json()["id"] != sid
    identity["user"] = CurrentUser(other_id, uuid.uuid4(), "student")
    assert (await client.get(f"/study-sessions/{other.json()['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_concurrent_create_and_send(api):
    client, _, _, factory = api
    results = await asyncio.gather(*[client.post("/study-sessions", json={"lesson_id": "newton-third-law"}) for _ in range(3)])
    assert all(r.status_code in (200, 201) for r in results)
    assert len({r.json()["id"] for r in results}) == 1
    sid = results[0].json()["id"]
    sent = await asyncio.gather(*[client.post(f"/study-sessions/{sid}/messages", json=command("hint")) for _ in range(2)])
    assert sorted(r.status_code for r in sent) == [200, 409]
    async with factory() as db:
        row = (await db.execute(select(ReviewSession))).scalar_one()
        assert row.version == 1 and row.state["hint_level"] == 1
