import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_db_session, require_teacher
from app.schemas.user import UserCreate, UserRead, UserSelfUpdate, UserUpdate
from app.services import user as user_svc

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead, summary="Get own profile")
async def get_me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """Returns the authenticated user's own record. Available to both roles."""
    user = await user_svc.get_me(current_user.id, db)
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead, summary="Update own profile")
async def update_me(
    body: UserSelfUpdate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """Update own `full_name` and/or `password`. Available to both roles."""
    user = await user_svc.update_me(current_user.id, body, db)
    return UserRead.model_validate(user)


@router.put(
    "/me/avatar",
    response_model=UserRead,
    summary="Upload own avatar",
    responses={
        400: {"description": "Unsupported file type (JPEG, PNG, WebP only)."},
        413: {"description": "File exceeds 5 MB limit."},
    },
)
async def upload_own_avatar(
    file: UploadFile,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """
    Upload a profile photo. Accepts JPEG, PNG or WebP, maximum 5 MB.
    Returns the updated user with `avatar_url` set to `/media/avatars/{id}.{ext}`.
    The frontend prefixes this path with the API base URL to build the full image URL.

    Available to both roles (own avatar only).
    """
    user = await user_svc.upload_own_avatar(current_user.id, file, db)
    return UserRead.model_validate(user)


@router.delete("/me/avatar", response_model=UserRead, summary="Remove own avatar")
async def remove_own_avatar(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """Remove own profile photo. Sets `avatar_url` to null. Available to both roles."""
    user = await user_svc.remove_own_avatar(current_user.id, db)
    return UserRead.model_validate(user)


@router.get(
    "",
    response_model=list[UserRead],
    summary="List users in school",
    responses={403: {"description": "Teacher access required."}},
)
async def list_users(
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
    role: str | None = Query(default=None, pattern="^(teacher|student)$", description="Filter by role"),
) -> list[UserRead]:
    """
    Returns all users in the teacher's school, ordered by name.

    - No `role` filter → returns teachers **and** students.
    - `?role=student` → students only.
    - `?role=teacher` → teachers only.

    Teacher access only.
    """
    users = await user_svc.list_users(current_user.school_id, role, db)
    return [UserRead.model_validate(u) for u in users]


@router.post(
    "",
    response_model=UserRead,
    status_code=201,
    summary="Create user",
    responses={
        409: {"description": "Email already registered."},
        403: {"description": "Teacher access required."},
    },
)
async def create_user(
    body: UserCreate,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """
    Create a new student or teacher in the same school as the requesting teacher.

    Teacher access only.
    """
    user = await user_svc.create_user(current_user.school_id, body, db)
    return UserRead.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get user by ID",
    responses={
        404: {"description": "User not found in this school."},
        403: {"description": "Teacher access required."},
    },
)
async def get_user(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """
    Fetch any user by ID — scoped to the teacher's school.
    Returns 404 if the user doesn't exist **or** belongs to a different school.

    Teacher access only.
    """
    user = await user_svc.get_user(user_id, current_user.school_id, db)
    return UserRead.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Update user",
    responses={
        404: {"description": "User not found in this school."},
        403: {"description": "Teacher access required."},
    },
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """
    Update another user's `full_name` or `is_active` status.
    To update your own record, use `PATCH /users/me`.

    Teacher access only.
    """
    user = await user_svc.update_user(user_id, current_user.school_id, body, db)
    return UserRead.model_validate(user)


@router.put(
    "/{user_id}/avatar",
    response_model=UserRead,
    summary="Upload avatar for user",
    responses={
        400: {"description": "Unsupported file type."},
        404: {"description": "User not found in this school."},
        413: {"description": "File exceeds 5 MB limit."},
        403: {"description": "Teacher access required."},
    },
)
async def upload_user_avatar(
    user_id: uuid.UUID,
    file: UploadFile,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """Upload a profile photo for any user in the school. Teacher access only."""
    user = await user_svc.upload_user_avatar(user_id, current_user.school_id, file, db)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}/avatar",
    response_model=UserRead,
    summary="Remove avatar for user",
    responses={
        404: {"description": "User not found in this school."},
        403: {"description": "Teacher access required."},
    },
)
async def remove_user_avatar(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """Remove a profile photo for any user in the school. Teacher access only."""
    user = await user_svc.remove_user_avatar(user_id, current_user.school_id, db)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    response_model=UserRead,
    summary="Deactivate user",
    responses={
        400: {"description": "Cannot deactivate your own account."},
        404: {"description": "User not found in this school."},
        403: {"description": "Teacher access required."},
    },
)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    """
    Soft-deactivate a user (sets `is_active=false`). Deactivated users cannot log in.
    Returns the updated user record.

    A teacher cannot deactivate their own account.
    Teacher access only.
    """
    user = await user_svc.deactivate_user(user_id, current_user.school_id, current_user.id, db)
    return UserRead.model_validate(user)
