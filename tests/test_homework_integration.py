"""Opt-in PostgreSQL route tests. Migrate a dedicated *_test database first.

Set TEST_DATABASE_URL to its asyncpg URL. Every fixture is rolled back, including
service commits; existing schools and users are never changed.
"""
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.deps import get_db_session
from app.core.security import create_access_token
from app.main import app
from app.models.school import School
from app.models.study_session import MasteryRecord
from app.models.user import User


@pytest_asyncio.fixture
async def homework_api():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL *_test database")
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").endswith("_test"):
        pytest.fail("Homework integration tests require a local database ending in _test")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False,
                                join_transaction_mode="create_savepoint") as db:
            schools = [School(name=f"Homework regression {uuid.uuid4()}") for _ in range(2)]
            db.add_all(schools)
            await db.flush()
            users = {}
            for key, role, school, active in [
                ("teacher", "teacher", schools[0], True),
                ("student", "student", schools[0], True),
                ("peer", "student", schools[0], True),
                ("inactive", "student", schools[0], False),
                ("foreign", "student", schools[1], True),
                ("foreign_teacher", "teacher", schools[1], True),
            ]:
                user = User(school_id=school.id, role=role, is_active=active,
                            email=f"{uuid.uuid4()}@example.test", full_name=key,
                            hashed_password="unused-in-token-auth-test")
                db.add(user)
                users[key] = user
            await db.flush()
            tokens = {key: {"Authorization": f"Bearer {create_access_token(user.id, user.school_id, user.role)}"}
                      for key, user in users.items()}

            async def session_override():
                yield db

            app.dependency_overrides[get_db_session] = session_override
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://test") as client:
                    yield client, db, users, tokens
            finally:
                app.dependency_overrides.pop(get_db_session, None)
        await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_homework_route_lifecycle_and_tenant_isolation(homework_api):
    client, db, users, tokens = homework_api
    teacher = tokens["teacher"]
    payload = {"lesson_id": "homework-regression", "title": "Regression quiz"}
    wrong_role = await client.post("/homework/assignments", headers=tokens["student"], json=payload)
    assert wrong_role.status_code == 403
    created = await client.post("/homework/assignments", headers=teacher, json=payload)
    assert created.status_code == 201, created.text
    path = f"/homework/assignments/{created.json()['id']}"
    assert (await client.get(path, headers=tokens["foreign_teacher"])).status_code == 404
    question = await client.post(path + "/questions", headers=teacher, json={
        "question_text": "2 + 2?", "options": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}],
        "correct_answer": "b", "concept_ref": "addition",
    })
    assert question.status_code == 201, question.text
    question_id = question.json()["id"]
    for rejected in ["foreign", "teacher", "inactive"]:
        distribution = await client.post(path + "/distribute", headers=teacher, json={
            "student_ids": [str(users["student"].id), str(users[rejected].id)],
        })
        assert distribution.status_code == 400, distribution.text
        assert (await client.get(path, headers=teacher)).json()["status"] == "draft"
    distributed = await client.post(path + "/distribute", headers=teacher, json={
        "student_ids": [str(users["student"].id)],
    })
    assert distributed.status_code == 200, distributed.text
    assert (await client.patch(path, headers=teacher, json={"title": "Changed"})).status_code == 409
    assignments = await client.get("/homework/me/assignments", headers=tokens["student"])
    received = next(row for row in assignments.json() if row["assignment_id"] == created.json()["id"])
    student_path = f"/homework/me/assignments/{received['id']}"
    assert (await client.get(student_path, headers=tokens["foreign"])).status_code == 404
    assert (await client.get(student_path, headers=tokens["peer"])).status_code == 403
    assert (await client.get(student_path, headers=teacher)).status_code == 403
    quiz = await client.get(student_path, headers=tokens["student"])
    assert quiz.status_code == 200
    assert "correct_answer" not in quiz.text
    hidden = await client.get(student_path + "/results", headers=tokens["student"])
    assert hidden.status_code == 409
    assert "correct_answer" not in hidden.text
    invalid = await client.post(student_path + "/submit", headers=tokens["student"], json={
        "answers": [{"question_id": question_id, "selected_option": "z"}],
    })
    assert invalid.status_code == 400, invalid.text
    answer = {"answers": [{"question_id": question_id, "selected_option": "b"}]}
    submitted = await client.post(student_path + "/submit", headers=tokens["student"], json=answer)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["score"] == 1
    assert submitted.json()["results"][0]["correct_answer"] == "b"
    saved = await client.get(student_path + "/results", headers=tokens["student"])
    assert saved.status_code == 200
    assert saved.json() == submitted.json()
    assert (await client.get(student_path + "/results", headers=tokens["foreign"])).status_code == 404
    assert (await client.get(student_path + "/results", headers=tokens["peer"])).status_code == 403
    assert (await client.get(student_path + "/results", headers=teacher)).status_code == 403
    assert "correct_answer" not in (await client.get(student_path, headers=tokens["student"])).text
    repeated = await client.post(student_path + "/submit", headers=tokens["student"], json=answer)
    assert repeated.status_code == 409
    mastery = (await db.execute(select(MasteryRecord).where(
        MasteryRecord.school_id == users["student"].school_id,
        MasteryRecord.student_id == users["student"].id,
        MasteryRecord.lesson_id == payload["lesson_id"],
    ))).scalar_one()
    assert mastery.attempt_count == 1
    assert mastery.correct_count == 1
    assert mastery.mastery_level == 1
    assert mastery.last_attempt_at is not None
