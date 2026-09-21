import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from fastapi import HTTPException, status


def _invalid_refresh_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": ErrorCode.UNAUTHORIZED, "message": "Invalid or expired refresh token"}},
    )


async def _issue_tokens(user: User, db: AsyncSession) -> tuple[str, str]:
    access_token = create_access_token(user.id, user.school_id, user.role)
    raw_refresh_token = generate_refresh_token()
    db.add(
        RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=refresh_token_expiry(),
        )
    )
    await db.commit()
    return access_token, raw_refresh_token


async def login(email: str, password: str, db: AsyncSession) -> tuple[str, str]:
    """
    Verify credentials and return (access_token, refresh_token).
    Raises HTTPException 401 on any failure — deliberately no detail on whether
    it was the email or password that was wrong (security best practice).
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.hashed_password) or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": ErrorCode.UNAUTHORIZED, "message": "Invalid credentials"}},
        )

    return await _issue_tokens(user, db)


async def refresh_access_token(raw_refresh_token: str, db: AsyncSession) -> tuple[str, str]:
    """
    Exchange a valid, unrevoked refresh token for a new (access_token, refresh_token)
    pair. The old refresh token is revoked on use (rotation) — replaying a stolen
    token after the legitimate client has already refreshed will fail, since it's
    already revoked. Also re-checks `is_active`, so a deactivated account loses the
    ability to mint new access tokens immediately rather than after the old one
    would have expired on its own.
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    stored = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if stored is None or stored.revoked_at is not None or stored.expires_at < now:
        raise _invalid_refresh_token()

    user = await db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise _invalid_refresh_token()

    stored.revoked_at = now
    await db.commit()

    return await _issue_tokens(user, db)


async def logout(raw_refresh_token: str, db: AsyncSession) -> None:
    """
    Revoke a refresh token so it can no longer be exchanged for new tokens.
    Idempotent: an unknown or already-revoked token is treated the same as a
    freshly revoked one, so the response never reveals whether the token existed.
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    stored = result.scalar_one_or_none()

    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(timezone.utc)
        await db.commit()
