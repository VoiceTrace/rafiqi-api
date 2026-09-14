import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserSelfUpdate, UserUpdate

_AVATAR_ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "User not found"}},
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": {"code": ErrorCode.CONFLICT, "message": "Email already registered"}},
    )


async def get_me(user_id: uuid.UUID, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise _not_found()
    return user


async def update_me(user_id: uuid.UUID, data: UserSelfUpdate, db: AsyncSession) -> User:
    user = await get_me(user_id, db)
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.password is not None:
        user.hashed_password = hash_password(data.password)
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(
    school_id: uuid.UUID,
    role: str | None,
    db: AsyncSession,
) -> list[User]:
    q = select(User).where(User.school_id == school_id)
    if role is not None:
        q = q.where(User.role == role)
    result = await db.execute(q.order_by(User.full_name))
    return list(result.scalars().all())


async def get_user(user_id: uuid.UUID, school_id: uuid.UUID, db: AsyncSession) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.school_id == school_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise _not_found()
    return user


async def create_user(school_id: uuid.UUID, data: UserCreate, db: AsyncSession) -> User:
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none() is not None:
        raise _conflict()

    user = User(
        id=uuid.uuid4(),
        school_id=school_id,
        email=data.email,
        full_name=data.full_name,
        role=data.role,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(
    user_id: uuid.UUID,
    school_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession,
) -> User:
    user = await get_user(user_id, school_id, db)
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.is_active is not None:
        user.is_active = data.is_active
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def _set_avatar(user: User, file: UploadFile, db: AsyncSession) -> User:
    content_type = file.content_type or ""
    if content_type not in _AVATAR_ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": "Unsupported type. Use JPEG, PNG or WebP."}},
        )

    data = await file.read()
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": "Image too large. Maximum 5 MB."}},
        )

    ext = _AVATAR_ALLOWED_TYPES[content_type]
    avatars_dir = Path(settings.MEDIA_DIR) / "avatars"

    # Remove any existing avatar file for this user (handles extension changes)
    for old_file in avatars_dir.glob(f"{user.id}.*"):
        old_file.unlink(missing_ok=True)

    (avatars_dir / f"{user.id}.{ext}").write_bytes(data)

    user.avatar_url = f"/media/avatars/{user.id}.{ext}"
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def _clear_avatar(user: User, db: AsyncSession) -> User:
    if user.avatar_url:
        Path(user.avatar_url.lstrip("/")).unlink(missing_ok=True)
    user.avatar_url = None
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def upload_own_avatar(user_id: uuid.UUID, file: UploadFile, db: AsyncSession) -> User:
    user = await get_me(user_id, db)
    return await _set_avatar(user, file, db)


async def remove_own_avatar(user_id: uuid.UUID, db: AsyncSession) -> User:
    user = await get_me(user_id, db)
    return await _clear_avatar(user, db)


async def upload_user_avatar(
    user_id: uuid.UUID, school_id: uuid.UUID, file: UploadFile, db: AsyncSession
) -> User:
    user = await get_user(user_id, school_id, db)
    return await _set_avatar(user, file, db)


async def remove_user_avatar(
    user_id: uuid.UUID, school_id: uuid.UUID, db: AsyncSession
) -> User:
    user = await get_user(user_id, school_id, db)
    return await _clear_avatar(user, db)


async def deactivate_user(
    user_id: uuid.UUID,
    school_id: uuid.UUID,
    actor_id: uuid.UUID,
    db: AsyncSession,
) -> User:
    if user_id == actor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": "Cannot deactivate your own account"}},
        )
    user = await get_user(user_id, school_id, db)
    user.is_active = False
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user
