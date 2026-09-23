"""Migration regression uses only the explicitly opted-in disposable review test DB."""
import json
import os
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, Table, MetaData
from app.core.database import Base
from app.core.config import settings
from app.services.review_catalog import catalog_seed


def test_catalog_fixture_and_seed_agree():
    fixture = Path(__file__).parents[1] / "alembic/versions/fixtures/review-catalog-v1.json"
    assert json.loads(fixture.read_text(encoding="utf-8")) == catalog_seed()


def test_catalog_migration_preserves_existing_session(monkeypatch):
    url = os.environ.get("REVIEW_TEST_DATABASE_URL", "")
    if not url.endswith("/rafiqi_review_test"):
        pytest.skip("Requires the dedicated /rafiqi_review_test database")
    sync_url = url.replace("postgresql+asyncpg", "postgresql")
    engine = create_engine(sync_url)
    with engine.begin() as db:
        assert db.scalar(text("select current_database()")) == "rafiqi_review_test"
        Base.metadata.drop_all(db)
        db.execute(text("DROP TABLE IF EXISTS alembic_version"))
    monkeypatch.setattr(settings, "DATABASE_URL_SYNC", sync_url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "e5a1b2c3d4e5")
    school, student, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    meta = MetaData()
    with engine.begin() as db:
        schools = Table("schools", meta, autoload_with=db)
        users = Table("users", meta, autoload_with=db)
        sessions = Table("review_sessions", meta, autoload_with=db)
        old_lesson = db.execute(text("SELECT content FROM review_lessons WHERE id='newton-third-law'")).scalar_one()
        db.execute(schools.insert().values(id=school, name="Migration test"))
        db.execute(users.insert().values(id=student, school_id=school, email="migration@example.test", full_name="Student", role="student", hashed_password="test"))
        state = {"index": 1, "attempts": 1, "hint_level": 0, "assistance": False, "resolved": True, "complete": True,
                 "requests": [str(uuid.uuid4())], "events": [{"role": "student", "kind": "answer", "question_id": "different-objects", "text": "different objects", "attempt": 1}]}
        db.execute(sessions.insert().values(id=sid, school_id=school, student_id=student, lesson_id="newton-third-law", content=old_lesson, state=state, version=4))
    command.upgrade(config, "head")
    with engine.connect() as db:
        row = db.execute(sessions.select().where(sessions.c.id == sid)).mappings().one()
        assert row["version"] == 4 and row["id"] == sid
        new_state = deepcopy(row["state"])
        assert new_state["events"][0].pop("concept_ref") == "action-reaction"
        assert new_state == state
        for loc in ("en", "ar"):
            assert row["content"][loc]["objective"] == old_lesson[loc]["objective"]
            assert row["content"][loc]["questions"][1]["keywords"] == old_lesson[loc]["questions"][1]["keywords"]
        assert db.scalar(text("select count(*) from review_lessons")) == 4
        assert db.scalar(text("select to_regclass('review_attempts')")) == "review_attempts"
        assert db.scalar(text("select to_regclass('mastery_records')")) == "mastery_records"
    command.downgrade(config, "-1")
    with engine.connect() as db:
        assert db.scalar(text("select to_regclass('mastery_records')")) is None
        assert db.scalar(text("select to_regclass('review_attempts')")) == "review_attempts"
    command.upgrade(config, "head")
    with engine.connect() as db:
        assert db.scalar(text("select count(*) from review_lessons")) == 4
        assert db.scalar(text("select to_regclass('review_attempts')")) == "review_attempts"
        assert db.scalar(text("select to_regclass('mastery_records')")) == "mastery_records"
        assert db.execute(sessions.select().where(sessions.c.id == sid)).mappings().one()["state"]["complete"]
    engine.dispose()
