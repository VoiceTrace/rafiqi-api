import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_student
from app.core.errors import ErrorCode
from app.schemas.review import CreateReview, LessonOut, Locale, ReviewMessage, SessionOut
from app.services import review as svc

router = APIRouter(tags=["study-review"])
Student = Annotated[CurrentUser, Depends(require_student)]
Database = Annotated[AsyncSession, Depends(get_db_session)]

_ERROR_CODES = {404: ErrorCode.NOT_FOUND, 409: ErrorCode.CONFLICT, 422: ErrorCode.VALIDATION_ERROR}


def _http(error: svc.ReviewError) -> HTTPException:
    code = _ERROR_CODES.get(error.status, ErrorCode.INTERNAL_ERROR)
    return HTTPException(status_code=error.status, detail={"error": {"code": code, "message": error.message}})


@router.get("/study-lessons", response_model=list[LessonOut])
async def lessons(user: Student, db: Database, locale: Locale = "en") -> list[LessonOut]:
    return await svc.list_lessons(db, locale)


@router.get("/study-lessons/{lesson_id}", response_model=LessonOut)
async def lesson(lesson_id: str, user: Student, db: Database, locale: Locale = "en") -> LessonOut:
    try:
        return await svc.get_lesson(db, lesson_id, locale)
    except svc.ReviewError as error:
        raise _http(error)


@router.post("/study-sessions", response_model=SessionOut)
async def create(
    body: CreateReview, user: Student, db: Database, response: Response, locale: Locale = "en",
) -> SessionOut:
    try:
        session, created = await svc.create_or_resume_session(db, user.id, user.school_id, body.lesson_id, locale)
    except svc.ReviewError as error:
        raise _http(error)
    if created:
        response.status_code = 201
    return session


@router.get("/study-sessions/by-lesson/{lesson_id}", response_model=SessionOut)
async def by_lesson(lesson_id: str, user: Student, db: Database, locale: Locale = "en") -> SessionOut:
    try:
        return await svc.get_session_by_lesson(db, user.id, user.school_id, lesson_id, locale)
    except svc.ReviewError as error:
        raise _http(error)


@router.get("/study-sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: uuid.UUID, user: Student, db: Database, locale: Locale = "en") -> SessionOut:
    try:
        return await svc.get_session(db, user.id, user.school_id, session_id, locale)
    except svc.ReviewError as error:
        raise _http(error)


@router.post("/study-sessions/{session_id}/messages", response_model=SessionOut)
async def send_message(session_id: uuid.UUID, body: ReviewMessage, user: Student, db: Database) -> SessionOut:
    try:
        return await svc.process_message(db, user.id, user.school_id, session_id, body)
    except svc.ReviewError as error:
        raise _http(error)
