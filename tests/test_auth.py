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
from datetime import datetime, timezone
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


def test_token_expires_in_6_hours():
    user_id, school_id = _make_ids()
    token = create_access_token(user_id, school_id, UserRole.STUDENT)
    payload = decode_access_token(token)

    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    now = datetime.now(timezone.utc)
    hours_until_expiry = (exp - now).total_seconds() / 3600

    # Should be close to 6h (allow 1 minute drift)
    assert 5.98 < hours_until_expiry <= 6.0


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
