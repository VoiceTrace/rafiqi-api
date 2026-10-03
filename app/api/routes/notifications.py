import uuid
from typing import Annotated
from datetime import timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentUser, get_current_user, get_db_session
from app.core.errors import ErrorCode
from app.schemas.notifications import CountOut, DestinationOut, InboxOut, InstallationIn, NotificationOut, ReadAll, ResultOut
from app.services import notifications as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])
User = Annotated[CurrentUser, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", response_model=InboxOut)
async def inbox(user: User, db: DB, unread_only: bool = False, cursor: str | None = Query(None, max_length=120), limit: int = Query(30, ge=1, le=100)):
    try:
        return await svc.list_inbox(db, user.school_id, user.id, unread_only, cursor, limit)
    except (ValueError, TypeError):
        raise HTTPException(422, detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": "Invalid cursor"}})


@router.get("/unread-count", response_model=CountOut)
async def count(user: User, db: DB):
    return await svc.unread_count(db, user.school_id, user.id)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def read(notification_id: uuid.UUID, user: User, db: DB):
    try:
        return await svc.mark_read(db, user.school_id, user.id, notification_id)
    except svc.NotificationNotFound:
        raise HTTPException(404, detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Notification not found"}})


@router.get("/{notification_id}/destination", response_model=DestinationOut)
async def destination(notification_id: uuid.UUID, user: User, db: DB):
    try:
        return await svc.destination(db, user.school_id, user.id, notification_id)
    except svc.NotificationNotFound:
        raise HTTPException(404, detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Destination unavailable"}})


@router.post("/read-all", response_model=ResultOut)
async def read_all(body: ReadAll, user: User, db: DB):
    if body.cutoff.tzinfo is None:
        raise HTTPException(422, detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": "Timezone required"}})
    return await svc.mark_all_read(db, user.school_id, user.id, body.cutoff.astimezone(timezone.utc))


@router.put("/installations/{installation_id}", response_model=ResultOut)
async def register(installation_id: uuid.UUID, body: InstallationIn, user: User, db: DB):
    try:
        return await svc.register_installation(db, user.school_id, user.id, installation_id, body)
    except svc.NotificationUnavailable:
        raise HTTPException(503, detail={"error": {"code": ErrorCode.INTERNAL_ERROR, "message": "Push registration unavailable"}})
    except svc.NotificationNotFound:
        raise HTTPException(403, detail={"error": {"code": ErrorCode.FORBIDDEN, "message": "Inactive account"}})


@router.delete("/installations/{installation_id}", response_model=ResultOut)
async def unregister(installation_id: uuid.UUID, user: User, db: DB):
    return await svc.unregister_installation(db, user.school_id, user.id, installation_id)
