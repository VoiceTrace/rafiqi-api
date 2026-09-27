import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import CurrentUser, get_db_session, require_teacher
from app.core.database import Base
from app.main import app
from app.models import School, User
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
            "other_student": other_school_student_id,
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
