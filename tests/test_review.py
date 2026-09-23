"""Mock behavior plus opt-in real PostgreSQL API tests (dedicated review test DB)."""
import asyncio
import json
import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api.deps import CurrentUser, require_student, get_db_session
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import School, User
from app.models.review import MasteryRecord, ReviewAttempt, ReviewLesson, ReviewSession
from app.schemas.review import ReviewMessage
from app.services.review import ReviewError, apply_message, initial_state, mastery_band, session_public
from app.services.review_seed import LESSON
from app.services.review_catalog import seed_catalog
from app.services.review_assessment import AssessmentMetadataError, classify_error


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
        with pytest.raises(ReviewError):
            apply_message(LESSON, state, ReviewMessage(**args))
    assert state == initial_state()
    for _ in range(3):
        state = apply_message(LESSON, state, ReviewMessage(**command("answer", option_id="none")))
    assert state["resolved"]
    assert LESSON["en"]["questions"][0]["explanation"] in state["events"][-1]["text"]
    with pytest.raises(ReviewError):
        apply_message(LESSON, state, ReviewMessage(**command("answer", option_id="equal")))


def test_questionless_chat_that_becomes_an_answer_has_a_clear_error():
    state = apply_message(LESSON, initial_state(), ReviewMessage(**command("answer", option_id="equal")))
    state = apply_message(LESSON, state, ReviewMessage(**command("next")))
    payload = command("chat", question=None, text="different objects")
    with pytest.raises(ReviewError) as error:
        apply_message(LESSON, state, ReviewMessage(**payload))
    assert error.value.code == "chat_question_id_required"
    assert state["attempts"] == 0 and state["resolved"] is False


def test_subject_error_taxonomy_is_stable_and_requires_concepts():
    question = LESSON["en"]["questions"][0]
    assert classify_error(subject_id="physics", question=question, option_id="smaller", score=0) == "force_pair_unequal_magnitude"
    assert classify_error(subject_id="physics", question=question, option_id="equal", score=1) is None
    without_concept = {**question, "concept_ref": None}
    with pytest.raises(AssessmentMetadataError, match="assessment_concept_required"):
        classify_error(subject_id="physics", question=without_concept, option_id="equal", score=1)


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0, "needs_support"), (0.49, "needs_support"), (0.5, "developing"),
     (0.79, "developing"), (0.8, "secure"), (1, "secure")],
)
def test_mvp_mastery_band_boundaries(score, expected):
    assert mastery_band(score) == expected


@pytest.mark.asyncio
async def test_role_gate_without_dependency_override():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/study-lessons", "/study-subjects", "/study-subjects/physics/chapters", "/study-mastery"):
            assert (await client.get(path)).status_code in (401, 403)
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
        await seed_catalog(db)
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


@pytest.mark.asyncio
async def test_attempt_capture_is_idempotent_scoped_and_taxonomy_backed(api):
    client, identity, other_id, factory = api
    session = (await client.post("/study-sessions", json={"lesson_id": "balanced-forces"})).json()
    payload = command("answer", question="balanced-forces-check", option_id="other")
    response = await client.post(f"/study-sessions/{session['id']}/messages", json=payload)
    assert response.status_code == 200
    assert (await client.post(f"/study-sessions/{session['id']}/messages", json=payload)).status_code == 200

    attempts = (await client.get(f"/study-sessions/{session['id']}/attempts")).json()
    assert len(attempts) == 1
    assert attempts[0]["concept_ref"] == "net-force"
    assert attempts[0]["correctness_score"] == 0
    assert attempts[0]["error_type"] == "balanced_force_means_stopped"
    assert attempts[0]["attempt_number"] == 1
    async with factory() as db:
        assert len((await db.execute(select(ReviewAttempt))).scalars().all()) == 1

    identity["user"] = CurrentUser(other_id, identity["user"].school_id, "student")
    assert (await client.get(f"/study-sessions/{session['id']}/attempts")).status_code == 404


@pytest.mark.asyncio
async def test_mastery_recalculates_from_latest_question_evidence(api):
    client, identity, other_id, factory = api
    session = (await client.post("/study-sessions", json={"lesson_id": "balanced-forces"})).json()

    wrong = command("answer", question="balanced-forces-check", option_id="other")
    assert (await client.post(f"/study-sessions/{session['id']}/messages", json=wrong)).status_code == 200
    first = (await client.get("/study-mastery")).json()
    assert len(first) == 1
    record = first[0]
    assert record["subject_id"] == "physics"
    assert record["concept_ref"] == "net-force"
    assert record["mastery_score"] == 0
    assert record["mastery_band"] == "needs_support"
    assert record["evidence_count"] == 1
    assert record["attempt_count"] == 1
    assert record["dominant_error_type"] == "balanced_force_means_stopped"
    assert record["calculation_version"] == "mvp-v1"

    correct = command("answer", version=1, question="balanced-forces-check", option_id="correct")
    assert (await client.post(f"/study-sessions/{session['id']}/messages", json=correct)).status_code == 200
    revised = (await client.get("/study-mastery")).json()[0]
    assert revised["id"] == record["id"]
    assert revised["mastery_score"] == 1
    assert revised["mastery_band"] == "secure"
    assert revised["evidence_count"] == 1
    assert revised["attempt_count"] == 2
    assert revised["dominant_error_type"] is None

    async with factory() as db:
        stored = (await db.execute(select(MasteryRecord))).scalars().all()
        assert len(stored) == 1

    identity["user"] = CurrentUser(other_id, identity["user"].school_id, "student")
    assert (await client.get("/study-mastery")).json() == []
    identity["user"] = CurrentUser(other_id, uuid.uuid4(), "student")
    assert (await client.get("/study-mastery")).json() == []


@pytest.mark.asyncio
async def test_mastery_averages_latest_evidence_per_question(api):
    client, _, _, _ = api
    session = (await client.post("/study-sessions", json={"lesson_id": "newton-third-law"})).json()
    payloads = [
        command("answer", option_id="equal"),
        command("next", version=1),
        command("answer", version=2, question="different-objects", text="different"),
    ]
    for payload in payloads:
        response = await client.post(f"/study-sessions/{session['id']}/messages", json=payload)
        assert response.status_code == 200, response.text

    mastery = (await client.get("/study-mastery")).json()
    assert len(mastery) == 1
    assert mastery[0]["concept_ref"] == "action-reaction"
    assert mastery[0]["mastery_score"] == 0.75
    assert mastery[0]["mastery_band"] == "developing"
    assert mastery[0]["evidence_count"] == 2
    assert mastery[0]["attempt_count"] == 2
    assert mastery[0]["dominant_error_type"] == "force_pair_incomplete_distinct_objects"


@pytest.mark.asyncio
async def test_catalog_hierarchy_locales_and_independent_sessions(api):
    client, _, _, factory = api
    subjects = (await client.get("/study-subjects")).json()
    arabic = (await client.get("/study-subjects?locale=ar")).json()
    assert {s["id"] for s in subjects} == {"physics", "mathematics"}
    assert [s["id"] for s in subjects] == [s["id"] for s in arabic]
    assert subjects[0]["title"] != arabic[0]["title"]
    found = []
    for subject in subjects:
        chapters = (await client.get(f"/study-subjects/{subject['id']}/chapters")).json()
        assert chapters
        for chapter in chapters:
            assert chapter["subject_id"] == subject["id"]
            en = (await client.get("/study-lessons", params={"chapter_id": chapter["id"]})).json()
            ar = (await client.get("/study-lessons", params={"chapter_id": chapter["id"], "locale": "ar"})).json()
            assert en and [x["id"] for x in en] == [x["id"] for x in ar]
            for lesson, translated in zip(en, ar):
                assert lesson["chapter_id"] == chapter["id"] and lesson["subject_id"] == subject["id"]
                assert lesson["objective"] != translated["objective"]
                assert lesson["concept_refs"][0]["id"] == translated["concept_refs"][0]["id"]
                assert "questions" not in lesson and "answer" not in json.dumps(lesson)
                found.append(lesson["id"])
    assert len(found) == 4 and len(set(found)) == 4
    for path in ("/study-subjects/missing/chapters", "/study-lessons?chapter_id=missing"):
        response = await client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"]["error"]["code"] == "not_found"
    assert (await client.get("/study-subjects?locale=xx")).status_code == 422
    first = (await client.post("/study-sessions", json={"lesson_id": "balanced-forces"})).json()
    second = (await client.post("/study-sessions", json={"lesson_id": "kinetic-energy"})).json()
    assert first["id"] != second["id"]
    result = await client.post(f"/study-sessions/{first['id']}/messages", json=command("answer", question="balanced-forces-check", option_id="correct"))
    assert result.status_code == 200, result.text
    assert result.json()["messages"][-1]["concept_ref"] == "net-force"
    assert (await client.get("/study-sessions/by-lesson/kinetic-energy")).json()["attempts"] == 0
    resumed = (await client.get("/study-sessions/by-lesson/balanced-forces")).json()
    assert resumed["id"] == first["id"] and resumed["attempts"] == 1
    async with factory() as db:
        await seed_catalog(db)
        await seed_catalog(db)
    assert len((await client.get("/study-lessons")).json()) == 4
    assert (await client.get("/study-sessions/by-lesson/balanced-forces")).json()["attempts"] == 1


def test_content_driven_hints_and_missing_translation():
    from copy import deepcopy
    from app.services.review import ReviewError
    content = deepcopy(LESSON)
    content["en"]["questions"][0]["hints"] = ["Only one hint"]
    state = apply_message(content, initial_state(), ReviewMessage(**command("hint")))
    session = SimpleNamespace(id=uuid.uuid4(), lesson_id="newton-third-law", version=1, content=content, state=state)
    assert session_public(session, "en")["can_hint"] is False
    del content["ar"]
    with pytest.raises(ReviewError) as error:
        session_public(session, "ar")
    assert error.value.code == "lesson_translation_unavailable"
