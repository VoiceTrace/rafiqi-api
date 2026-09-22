import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentUser, get_db_session, require_student
from app.models.review import ReviewLesson, ReviewSession
from app.schemas.review import CreateReview, Locale, ReviewMessage
from app.services.review import apply_message, initial_state, lesson_public, session_public

router = APIRouter(tags=["study-review"])
Student = Annotated[CurrentUser, Depends(require_student)]
Database = Annotated[AsyncSession, Depends(get_db_session)]


async def owned(db, user, session_id=None, lesson_id=None, lock=False):
    stmt = select(ReviewSession).where(ReviewSession.school_id == user.school_id, ReviewSession.student_id == user.id)
    stmt = stmt.where(ReviewSession.id == session_id) if session_id else stmt.where(ReviewSession.lesson_id == lesson_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("/study-lessons")
async def lessons(user: Student, db: Database, locale: Locale = "en"):
    rows = (await db.execute(select(ReviewLesson).order_by(ReviewLesson.id))).scalars().all()
    return [lesson_public(row.id, row.content, locale) for row in rows]


@router.get("/study-lessons/{lesson_id}")
async def lesson(lesson_id: str, user: Student, db: Database, locale: Locale = "en"):
    row = await db.get(ReviewLesson, lesson_id)
    if not row:
        raise HTTPException(404, "lesson_not_found")
    return lesson_public(row.id, row.content, locale)


@router.post("/study-sessions")
async def create(body: CreateReview, user: Student, db: Database, response: Response, locale: Locale = "en"):
    session = await owned(db, user, lesson_id=body.lesson_id)
    if session:
        return session_public(session, locale)
    lesson = await db.get(ReviewLesson, body.lesson_id)
    if not lesson:
        raise HTTPException(404, "lesson_not_found")
    session = ReviewSession(school_id=user.school_id, student_id=user.id, lesson_id=lesson.id,
                            content=lesson.content, state=initial_state(), version=0)
    db.add(session)
    try:
        await db.commit()
        await db.refresh(session)
        response.status_code = 201
    except IntegrityError:
        await db.rollback()
        session = await owned(db, user, lesson_id=body.lesson_id)
        if session is None:
            raise
    return session_public(session, locale)


@router.get("/study-sessions/by-lesson/{lesson_id}")
async def by_lesson(lesson_id: str, user: Student, db: Database, locale: Locale = "en"):
    session = await owned(db, user, lesson_id=lesson_id)
    if not session:
        raise HTTPException(404, "session_not_found")
    return session_public(session, locale)


@router.get("/study-sessions/{session_id}")
async def get_session(session_id: uuid.UUID, user: Student, db: Database, locale: Locale = "en"):
    session = await owned(db, user, session_id=session_id)
    if not session:
        raise HTTPException(404, "session_not_found")
    return session_public(session, locale)


@router.post("/study-sessions/{session_id}/messages")
async def send_message(session_id: uuid.UUID, body: ReviewMessage, user: Student, db: Database):
    session = await owned(db, user, session_id=session_id, lock=True)
    if not session:
        raise HTTPException(404, "session_not_found")
    if str(body.request_id) in session.state["requests"]:
        return session_public(session, body.locale)
    if session.version != body.expected_version:
        raise HTTPException(409, "stale_session")
    session.state = apply_message(session.content, session.state, body)
    session.version += 1
    await db.commit()
    await db.refresh(session)
    return session_public(session, body.locale)

