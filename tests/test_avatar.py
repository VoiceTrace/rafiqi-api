"""
Avatar upload/remove tests — no database or disk I/O required.

Tests cover:
- _set_avatar: rejects unsupported MIME types (400)
- _set_avatar: rejects files over 5 MB (413)
- _set_avatar: accepts JPEG, PNG, WebP
- _clear_avatar: sets avatar_url to None, tolerates missing file
- avatar_url included in UserRead schema
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.user import UserRead
from app.services.user import _clear_avatar, _set_avatar


class _FakeUpload:
    """Minimal UploadFile stand-in for testing."""
    def __init__(self, content_type: str, data: bytes = b"fake"):
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


def _fake_user(**kwargs) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.avatar_url = kwargs.get("avatar_url", None)
    return user


# ---------------------------------------------------------------------------
# _set_avatar: MIME type validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_avatar_rejects_unsupported_type():
    user = _fake_user()
    file = _FakeUpload(content_type="image/gif")
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await _set_avatar(user, file, mock_db)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_set_avatar_rejects_pdf():
    user = _fake_user()
    file = _FakeUpload(content_type="application/pdf")
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await _set_avatar(user, file, mock_db)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _set_avatar: size limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_avatar_rejects_oversized_file():
    user = _fake_user()
    over_limit = b"x" * (5 * 1024 * 1024 + 1)  # 5 MB + 1 byte
    file = _FakeUpload(content_type="image/jpeg", data=over_limit)
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await _set_avatar(user, file, mock_db)

    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# _set_avatar: accepted types write file + update DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("content_type,ext", [
    ("image/jpeg", "jpg"),
    ("image/png", "png"),
    ("image/webp", "webp"),
])
async def test_set_avatar_accepts_valid_types(content_type, ext):
    user = _fake_user()
    file = _FakeUpload(content_type=content_type, data=b"imgdata")
    mock_db = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=None)

    with patch("app.services.user.Path") as MockPath:
        # avatars_dir.glob() returns nothing (no old files)
        mock_avatars_dir = MagicMock()
        mock_avatars_dir.glob.return_value = []
        mock_file_obj = MagicMock()
        mock_avatars_dir.__truediv__ = MagicMock(return_value=mock_file_obj)
        MockPath.return_value.__truediv__.return_value = mock_avatars_dir

        await _set_avatar(user, file, mock_db)

    assert user.avatar_url == f"/media/avatars/{user.id}.{ext}"
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _clear_avatar: sets avatar_url to None, tolerates no file on disk
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_avatar_sets_url_to_none():
    user = _fake_user(avatar_url="/media/avatars/some-id.jpg")
    mock_db = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=None)

    with patch("app.services.user.Path") as MockPath:
        MockPath.return_value.unlink = MagicMock()
        await _clear_avatar(user, mock_db)

    assert user.avatar_url is None
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_avatar_when_no_existing_avatar():
    user = _fake_user(avatar_url=None)
    mock_db = AsyncMock()
    mock_db.refresh = AsyncMock(return_value=None)

    # Should not raise even though there is nothing to delete
    await _clear_avatar(user, mock_db)

    assert user.avatar_url is None


# ---------------------------------------------------------------------------
# Schema: avatar_url field is present and nullable
# ---------------------------------------------------------------------------

def test_user_read_includes_avatar_url():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "school_id": uuid.uuid4(),
        "email": "a@b.com",
        "full_name": "Test",
        "role": "student",
        "is_active": True,
        "avatar_url": None,
        "created_at": now,
        "updated_at": now,
    }
    read = UserRead(**data)
    assert read.avatar_url is None

    data["avatar_url"] = "/media/avatars/abc.jpg"
    read = UserRead(**data)
    assert read.avatar_url == "/media/avatars/abc.jpg"
