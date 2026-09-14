"""
User CRUD tests — no database required.

Tests cover:
- Schema validation: email, password length, role enum
- Service: duplicate email raises 409
- Service: deactivate_user raises 400 when actor targets themselves
- Service: get_user raises 404 for mismatched school_id (tenant isolation)
- Auth: deactivated user cannot login
- Role enforcement: student token rejected on teacher-only deps
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.user import UserCreate, UserSelfUpdate, UserUpdate
from app.services.user import create_user, deactivate_user, get_user


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_user_create_rejects_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", full_name="Test", role="student", password="password123")


def test_user_create_rejects_short_password():
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.com", full_name="Test", role="student", password="short")


def test_user_create_rejects_invalid_role():
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.com", full_name="Test", role="admin", password="password123")


def test_user_self_update_all_fields_optional():
    update = UserSelfUpdate()
    assert update.full_name is None
    assert update.password is None


def test_user_update_all_fields_optional():
    update = UserUpdate()
    assert update.full_name is None
    assert update.is_active is None


# ---------------------------------------------------------------------------
# Service: create_user — duplicate email → 409
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_user_raises_409_on_duplicate_email():
    data = UserCreate(
        email="dup@school.sa",
        full_name="Dup User",
        role="student",
        password="password123",
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock()  # existing user

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await create_user(uuid.uuid4(), data, mock_db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"]["code"] == "conflict"


# ---------------------------------------------------------------------------
# Service: deactivate_user — cannot deactivate self → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deactivate_self_raises_400():
    actor_id = uuid.uuid4()
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await deactivate_user(
            user_id=actor_id,
            school_id=uuid.uuid4(),
            actor_id=actor_id,
            db=mock_db,
        )

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Service: get_user — different school_id → 404 (tenant isolation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_wrong_school_raises_404():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # school_id filter excluded the row

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await get_user(uuid.uuid4(), school_id=uuid.uuid4(), db=mock_db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Auth: deactivated user cannot login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inactive_user_cannot_login():
    from app.core.security import hash_password
    from app.services.auth import login

    inactive_user = MagicMock()
    inactive_user.hashed_password = hash_password("pass1234")
    inactive_user.is_active = False

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = inactive_user

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await login("user@school.sa", "pass1234", mock_db)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Role enforcement: student denied teacher-only deps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_student_token_rejected_by_require_teacher():
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import require_teacher
    from app.core.security import create_access_token
    from app.models.user import UserRole

    token = create_access_token(uuid.uuid4(), uuid.uuid4(), UserRole.STUDENT)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await require_teacher(creds)

    assert exc_info.value.status_code == 403
