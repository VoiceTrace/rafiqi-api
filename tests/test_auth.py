"""
Auth tests — no database required.

Tests cover:
- Password hashing and verification
- JWT creation and decoding (including expiry claim)
- Token payload contains expected fields
- decode rejects a tampered token
- deps: correct role passes, wrong role raises 403
- deps: missing/invalid token raises 401
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.api.deps import CurrentUser, require_student, require_teacher
from app.models.user import UserRole


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def test_hash_and_verify_password():
    hashed = hash_password("secret123")
    assert verify_password("secret123", hashed)


def test_wrong_password_fails():
    hashed = hash_password("secret123")
    assert not verify_password("wrong", hashed)


# ---------------------------------------------------------------------------
# JWT creation and decoding
# ---------------------------------------------------------------------------

def _make_ids():
    return uuid.uuid4(), uuid.uuid4()


def test_create_and_decode_token():
    user_id, school_id = _make_ids()
    token = create_access_token(user_id, school_id, UserRole.TEACHER)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["school_id"] == str(school_id)
    assert payload["role"] == UserRole.TEACHER


def test_token_expires_in_configured_minutes():
    user_id, school_id = _make_ids()
    token = create_access_token(user_id, school_id, UserRole.STUDENT)
    payload = decode_access_token(token)

    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    now = datetime.now(timezone.utc)
    minutes_until_expiry = (exp - now).total_seconds() / 60

    # Should be close to ACCESS_TOKEN_EXPIRE_MINUTES (allow a few seconds drift)
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES - 0.1 < minutes_until_expiry <= settings.ACCESS_TOKEN_EXPIRE_MINUTES


def test_tampered_token_raises():
    user_id, school_id = _make_ids()
    token = create_access_token(user_id, school_id, UserRole.TEACHER)
    tampered = token[:-4] + "XXXX"

    from jose import JWTError
    with pytest.raises(JWTError):
        decode_access_token(tampered)


def test_token_signed_with_wrong_key_raises():
    user_id, school_id = _make_ids()
    payload = {"sub": str(user_id), "school_id": str(school_id), "role": "teacher"}
    bad_token = jwt.encode(payload, "wrong-secret", algorithm=settings.ALGORITHM)

    from jose import JWTError
    with pytest.raises(JWTError):
        decode_access_token(bad_token)


# ---------------------------------------------------------------------------
# deps: role enforcement
# ---------------------------------------------------------------------------

def _credentials_for(user_id, school_id, role) -> HTTPAuthorizationCredentials:
    token = create_access_token(user_id, school_id, role)
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_require_teacher_passes_for_teacher():
    user_id, school_id = _make_ids()
    creds = _credentials_for(user_id, school_id, UserRole.TEACHER)
    user = await require_teacher(creds)
    assert user.role == UserRole.TEACHER
    assert user.school_id == school_id


@pytest.mark.asyncio
async def test_require_teacher_rejects_student():
    user_id, school_id = _make_ids()
    creds = _credentials_for(user_id, school_id, UserRole.STUDENT)
    with pytest.raises(HTTPException) as exc_info:
        await require_teacher(creds)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_student_passes_for_student():
    user_id, school_id = _make_ids()
    creds = _credentials_for(user_id, school_id, UserRole.STUDENT)
    user = await require_student(creds)
    assert user.role == UserRole.STUDENT


@pytest.mark.asyncio
async def test_require_student_rejects_teacher():
    user_id, school_id = _make_ids()
    creds = _credentials_for(user_id, school_id, UserRole.TEACHER)
    with pytest.raises(HTTPException) as exc_info:
        await require_student(creds)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_invalid_token_raises_401():
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not.a.token")
    with pytest.raises(HTTPException) as exc_info:
        await require_teacher(creds)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tenant isolation: school_id is always in the token
# ---------------------------------------------------------------------------

def test_token_always_carries_school_id():
    user_id, school_id = _make_ids()
    for role in [UserRole.TEACHER, UserRole.STUDENT]:
        token = create_access_token(user_id, school_id, role)
        payload = decode_access_token(token)
        assert "school_id" in payload, f"school_id missing for role={role}"


# ---------------------------------------------------------------------------
# Refresh tokens: generation/hashing
# ---------------------------------------------------------------------------

def test_generate_refresh_token_is_unique_and_high_entropy():
    from app.core.security import generate_refresh_token

    a, b = generate_refresh_token(), generate_refresh_token()
    assert a != b
    assert len(a) > 32


def test_hash_refresh_token_is_deterministic_sha256():
    from app.core.security import hash_refresh_token

    token = "some-refresh-token-value"
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert len(hash_refresh_token(token)) == 64  # sha256 hex digest


# ---------------------------------------------------------------------------
# Refresh token service flow (mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_rejects_unknown_token():
    from app.services.auth import refresh_access_token

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await refresh_access_token("not-a-real-token", mock_db)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_revoked_token():
    from app.models.refresh_token import RefreshToken
    from app.services.auth import refresh_access_token

    stored = RefreshToken(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="irrelevant",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=datetime.now(timezone.utc),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stored
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await refresh_access_token("some-token", mock_db)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_expired_token():
    from app.models.refresh_token import RefreshToken
    from app.services.auth import refresh_access_token

    stored = RefreshToken(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="irrelevant",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        revoked_at=None,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stored
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await refresh_access_token("some-token", mock_db)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_inactive_user():
    from app.models.refresh_token import RefreshToken
    from app.services.auth import refresh_access_token

    user_id, school_id = _make_ids()
    stored = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash="irrelevant",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=None,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stored
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    inactive_user = MagicMock()
    inactive_user.is_active = False
    mock_db.get.return_value = inactive_user

    with pytest.raises(HTTPException) as exc_info:
        await refresh_access_token("some-token", mock_db)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_and_returns_new_pair():
    from app.models.refresh_token import RefreshToken
    from app.models.user import UserRole
    from app.services.auth import refresh_access_token

    user_id, school_id = _make_ids()
    stored = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash="irrelevant",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=None,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stored
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()  # db.add() is sync on a real AsyncSession

    active_user = MagicMock()
    active_user.id = user_id
    active_user.school_id = school_id
    active_user.role = UserRole.STUDENT
    active_user.is_active = True
    mock_db.get.return_value = active_user

    access_token, new_refresh_token = await refresh_access_token("old-token", mock_db)

    assert stored.revoked_at is not None  # old token rotated out
    assert access_token
    assert new_refresh_token
    payload = decode_access_token(access_token)
    assert payload["sub"] == str(user_id)


# ---------------------------------------------------------------------------
# Logout service flow (mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logout_revokes_known_token():
    from app.models.refresh_token import RefreshToken
    from app.services.auth import logout

    stored = RefreshToken(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="irrelevant",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=None,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stored
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    await logout("some-token", mock_db)

    assert stored.revoked_at is not None
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_logout_is_idempotent_for_unknown_token():
    from app.services.auth import logout

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    await logout("never-issued-token", mock_db)  # should not raise

    mock_db.commit.assert_not_awaited()
