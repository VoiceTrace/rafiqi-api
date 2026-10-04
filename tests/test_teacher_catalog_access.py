import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session
from app.core.security import create_access_token
from app.main import app


@pytest.mark.asyncio
async def test_teacher_can_read_global_study_catalog(monkeypatch):
    async def database():
        yield object()

    async def subjects(_db, locale):
        return [{"id": "physics", "title": "الفيزياء" if locale == "ar" else "Physics"}]

    monkeypatch.setattr("app.api.routes.review.catalog.list_subjects", subjects)
    app.dependency_overrides[get_db_session] = database
    token = create_access_token(uuid.uuid4(), uuid.uuid4(), "teacher")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/study-subjects?locale=ar", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json() == [{"id": "physics", "title": "الفيزياء"}]
    finally:
        app.dependency_overrides.clear()
