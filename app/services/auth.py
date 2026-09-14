from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode
from app.core.security import create_access_token, verify_password
from app.models.user import User
from fastapi import HTTPException, status


async def login(email: str, password: str, db: AsyncSession) -> str:
    """
    Verify credentials and return a signed JWT.
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

    return create_access_token(user.id, user.school_id, user.role)
