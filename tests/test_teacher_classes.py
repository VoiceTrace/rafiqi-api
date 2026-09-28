import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import CurrentUser, get_db_session, require_teacher
from app.core.database import Base
from app.main import app
from app.models import ReviewAttempt, ReviewLesson, ReviewSession, ReviewSessionSummary, School, User
from app.services.review_catalog import seed_catalog


@pytest_asyncio.fixture
async def class_api():
    url = os.environ.get("REVIEW_TEST_DATABASE_URL", "")
    if not url.endswith("/rafiqi_review_test"):
        pytest.skip("Set REVIEW_TEST_DATABASE_URL to a dedicated /rafiqi_review_test database")
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    school_id = uuid.uuid4()
    other_school_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    other_teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    second_student_id = uuid.uuid4()
    other_school_student_id = uuid.uuid4()
    async with factory() as db:
        db.add_all(
            [School(id=school_id, name="Teacher test"), School(id=other_school_id, name="Other school")]
        )
        await db.flush()
        db.add_all(
            [
                User(id=teacher_id, school_id=school_id, email="teacher@class.test", full_name="Teacher", role="teacher", hashed_password="test"),
                User(id=other_teacher_id, school_id=school_id, email="other.teacher@class.test", full_name="Other Teacher", role="teacher", hashed_password="test"),
                User(id=student_id, school_id=school_id, email="student@class.test", full_name="Student", role="student", hashed_password="test"),
                User(id=second_student_id, school_id=school_id, email="second.student@class.test", full_name="Second Student", role="student", hashed_password="test"),
                User(id=other_school_student_id, school_id=other_school_id, email="student@other.test", full_name="Other Student", role="student", hashed_password="test"),
            ]
        )
        await seed_catalog(db)
        await db.commit()

    identity = {"user": CurrentUser(teacher_id, school_id, "teacher")}

    async def teacher():
        return identity["user"]

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[require_teacher] = teacher
    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, identity, {
            "school": school_id,
            "other_school": other_school_id,
            "teacher": teacher_id,
            "other_teacher": other_teacher_id,
            "student": student_id,
            "second_student": second_student_id,
            "other_student": other_school_student_id,
            "factory": factory,
        }
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_teacher_class_enrollment_lifecycle(class_api):
    client, _, ids = class_api
    created = await client.post(
        "/teacher/classes",
        json={
            "name": "Grade 10 Physics A",
            "grade_level": "Grade 10",
            "subject_id": "physics",
            "academic_year": "2026-2027",
        },
    )
    assert created.status_code == 201, created.text
    class_id = created.json()["id"]
    assert created.json()["student_count"] == 0

    enrolled = await client.post(
        f"/teacher/classes/{class_id}/students", json={"student_id": str(ids["student"])}
    )
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.json()["is_active"] is True

    listed = await client.get("/teacher/classes")
    assert listed.status_code == 200
    assert listed.json()[0]["student_count"] == 1
    roster = await client.get(f"/teacher/classes/{class_id}/students")
    assert [student["id"] for student in roster.json()] == [str(ids["student"])]

    duplicate = await client.post(
        f"/teacher/classes/{class_id}/students", json={"student_id": str(ids["student"])}
    )
    assert duplicate.status_code == 409

    removed = await client.delete(f"/teacher/classes/{class_id}/students/{ids['student']}")
    assert removed.status_code == 200 and removed.json()["is_active"] is False
    assert (await client.get(f"/teacher/classes/{class_id}/students")).json() == []

    restored = await client.post(
        f"/teacher/classes/{class_id}/students", json={"student_id": str(ids["student"])}
    )
    assert restored.status_code == 201 and restored.json()["is_active"] is True


@pytest.mark.asyncio
async def test_class_access_is_teacher_owned_and_school_scoped(class_api):
    client, identity, ids = class_api
    created = await client.post(
        "/teacher/classes",
        json={
            "name": "Physics A",
            "grade_level": "Grade 10",
            "subject_id": "physics",
            "academic_year": "2026-2027",
        },
    )
    class_id = created.json()["id"]

    outside = await client.post(
        f"/teacher/classes/{class_id}/students",
        json={"student_id": str(ids["other_student"])},
    )
    assert outside.status_code == 404

    identity["user"] = CurrentUser(ids["other_teacher"], ids["school"], "teacher")
    assert (await client.get(f"/teacher/classes/{class_id}")).status_code == 404
    assert (await client.get(f"/teacher/classes/{class_id}/students")).status_code == 404
    assert (await client.patch(f"/teacher/classes/{class_id}", json={"name": "Hijacked"})).status_code == 404

    identity["user"] = CurrentUser(ids["teacher"], ids["other_school"], "teacher")
    assert (await client.get(f"/teacher/classes/{class_id}")).status_code == 404


@pytest.mark.asyncio
async def test_class_catalog_and_uniqueness_validation(class_api):
    client, _, _ = class_api
    body = {
        "name": "Grade 10 Physics A",
        "grade_level": "Grade 10",
        "subject_id": "physics",
        "academic_year": "2026-2027",
    }
    assert (await client.post("/teacher/classes", json=body)).status_code == 201
    assert (await client.post("/teacher/classes", json=body)).status_code == 409
    invalid = {**body, "name": "Unknown", "subject_id": "not-a-subject"}
    assert (await client.post("/teacher/classes", json=invalid)).status_code == 404


@pytest.mark.asyncio
async def test_class_and_student_mastery_use_latest_filtered_evidence(class_api):
    client, identity, ids = class_api
    created = await client.post(
        "/teacher/classes",
        json={
            "name": "Evidence class",
            "grade_level": "Grade 10",
            "subject_id": "physics",
            "academic_year": "2026-2027",
        },
    )
    class_id = created.json()["id"]
    for student_id in (ids["student"], ids["second_student"]):
        assert (
            await client.post(
                f"/teacher/classes/{class_id}/students",
                json={"student_id": str(student_id)},
            )
        ).status_code == 201

    factory = ids["factory"]
    async with factory() as db:
        lesson = await db.get(ReviewLesson, "newton-third-law")
        session = ReviewSession(
            id=uuid.uuid4(),
            school_id=ids["school"],
            student_id=ids["student"],
            lesson_id=lesson.id,
            content=lesson.content,
            state={},
            version=1,
        )
        db.add(session)
        await db.flush()
        when = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
        db.add_all(
            [
                ReviewAttempt(
                    school_id=ids["school"], student_id=ids["student"], session_id=session.id,
                    lesson_id=lesson.id, request_id=uuid.uuid4(), question_id="force-pairs",
                    concept_ref="action-reaction", response_text="wrong", option_id="smaller",
                    correctness_score=0, error_type="force_pair_unequal_magnitude", hint_level=0,
                    assisted=False, attempt_number=1, locale="en", created_at=when,
                ),
                ReviewAttempt(
                    school_id=ids["school"], student_id=ids["student"], session_id=session.id,
                    lesson_id=lesson.id, request_id=uuid.uuid4(), question_id="force-pairs",
                    concept_ref="action-reaction", response_text="equal", option_id="equal",
                    correctness_score=1, error_type=None, hint_level=1,
                    assisted=True, attempt_number=2, locale="en", created_at=when,
                ),
                ReviewAttempt(
                    school_id=ids["school"], student_id=ids["student"], session_id=session.id,
                    lesson_id=lesson.id, request_id=uuid.uuid4(), question_id="different-objects",
                    concept_ref="action-reaction", response_text="different objects", option_id=None,
                    correctness_score=0.5, error_type="force_pair_incomplete_distinct_objects", hint_level=0,
                    assisted=False, attempt_number=1, locale="en", created_at=when,
                ),
            ]
        )
        db.add(
            ReviewSessionSummary(
                school_id=ids["school"],
                student_id=ids["student"],
                session_id=session.id,
                lesson_id=lesson.id,
                concepts=[
                    {
                        "concept_ref": "action-reaction",
                        "mastery_band": "developing",
                        "completed_with_support": True,
                    }
                ],
                total_attempts=3,
                calculation_version="mvp-v1",
                completed_at=when,
            )
        )
        await db.commit()

    report = await client.get(
        f"/teacher/classes/{class_id}/mastery",
        params={"lesson_id": "newton-third-law", "from": "2026-09-01", "to": "2026-09-30"},
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["enrolled_student_count"] == 2
    assert body["students_with_evidence"] == 1
    assert body["average_mastery"] == 0.75
    assert body["band_counts"] == {
        "needs_support": 0, "developing": 1, "secure": 0, "no_evidence": 1
    }
    student = next(item for item in body["students"] if item["student_id"] == str(ids["student"]))
    assert student["evidence_count"] == 2
    assert student["attempt_count"] == 3
    assert student["assisted_evidence_count"] == 1
    assert student["dominant_error_type"] in {
        "force_pair_unequal_magnitude", "force_pair_incomplete_distinct_objects"
    }
    assert body["concepts"][0]["title"] == "Action and reaction"

    detail = await client.get(
        f"/teacher/students/{ids['student']}/mastery",
        params={"class_id": class_id, "lesson_id": "newton-third-law", "locale": "ar"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["student"]["mastery_band"] == "developing"
    assert detail.json()["concepts"][0]["title"] == "الفعل ورد الفعل"

    invalid = await client.get(
        f"/teacher/classes/{class_id}/mastery",
        params={"from": "2026-10-01", "to": "2026-09-01"},
    )
    assert invalid.status_code == 422

    sessions = await client.get(
        f"/teacher/classes/{class_id}/review-sessions",
        params={"lesson_id": "newton-third-law", "mastery_outcome": "developing"},
    )
    assert sessions.status_code == 200, sessions.text
    assert sessions.json()["total"] == 1
    session_item = sessions.json()["items"][0]
    assert session_item["session_id"] == str(session.id)
    assert session_item["dominant_error_type"] in {
        "force_pair_unequal_magnitude", "force_pair_incomplete_distinct_objects"
    }

    student_sessions = await client.get(
        f"/teacher/students/{ids['student']}/review-sessions",
        params={"class_id": class_id, "locale": "ar"},
    )
    assert student_sessions.status_code == 200
    assert student_sessions.json()["items"][0]["concepts"][0]["title"] == "الفعل ورد الفعل"

    session_detail = await client.get(
        f"/teacher/review-sessions/{session.id}", params={"class_id": class_id}
    )
    assert session_detail.status_code == 200, session_detail.text
    assert len(session_detail.json()["attempts"]) == 3
    first_force_attempt = next(
        item for item in session_detail.json()["attempts"]
        if item["question_id"] == "force-pairs" and item["attempt_number"] == 1
    )
    assert first_force_attempt["response_text"] == "wrong"

    misconceptions = await client.get(
        f"/teacher/classes/{class_id}/misconceptions",
        params={"lesson_id": "newton-third-law", "locale": "en"},
    )
    assert misconceptions.status_code == 200, misconceptions.text
    assert misconceptions.json()["students_with_evidence"] == 1
    assert sum(item["attempt_count"] for item in misconceptions.json()["items"]) == 2
    assert all(item["percentage"] == 100 for item in misconceptions.json()["items"])

    identity["user"] = CurrentUser(ids["other_teacher"], ids["school"], "teacher")
    assert (await client.get(f"/teacher/classes/{class_id}/mastery")).status_code == 404
    assert (
        await client.get(
            f"/teacher/students/{ids['student']}/mastery", params={"class_id": class_id}
        )
    ).status_code == 404
    assert (await client.get(f"/teacher/classes/{class_id}/review-sessions")).status_code == 404
    assert (
        await client.get(
            f"/teacher/review-sessions/{session.id}", params={"class_id": class_id}
        )
    ).status_code == 404
