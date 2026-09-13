import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ErrorCode
from app.core.security import decode_access_token
from app.models.user import UserRole

bearer_scheme = HTTPBearer()


@dataclass
class CurrentUser:
    id: uuid.UUID
    school_id: uuid.UUID
    role: str


def _extract_user(credentials: HTTPAuthorizationCredentials) -> CurrentUser:
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": ErrorCode.UNAUTHORIZED, "message": "Invalid or expired token"}},
        )
    return CurrentUser(
        id=uuid.UUID(payload["sub"]),
        school_id=uuid.UUID(payload["school_id"]),
        role=payload["role"],
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    return _extract_user(credentials)


async def require_teacher(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    user = _extract_user(credentials)
    if user.role != UserRole.TEACHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": ErrorCode.FORBIDDEN, "message": "Teacher access required"}},
        )
    return user


async def require_student(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    user = _extract_user(credentials)
    if user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": ErrorCode.FORBIDDEN, "message": "Student access required"}},
        )
    return user


# DB session dependency — re-exported here so routes only import from deps
async def get_db_session(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    return db
