import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_teacher
from app.core.errors import ErrorCode
from app.schemas.teacher_insights import ClassMasteryOut, StudentMasteryOut
from app.services import teacher_insights as svc

router = APIRouter(prefix="/teacher", tags=["teacher insights"])
Teacher = Annotated[CurrentUser, Depends(require_teacher)]
DB = Annotated[AsyncSession, Depends(get_db_session)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Class or student not found"}},
    )


def _invalid_dates() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": "The from date must not be after the to date"}},
    )


@router.get("/classes/{class_id}/mastery", response_model=ClassMasteryOut)
async def class_mastery(
    class_id: uuid.UUID,
    teacher: Teacher,
    db: DB,
    subject_id: str | None = Query(default=None, max_length=100),
    chapter_id: str | None = Query(default=None, max_length=100),
    lesson_id: str | None = Query(default=None, max_length=100),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    locale: Literal["en", "ar"] = Query(default="en"),
) -> ClassMasteryOut:
    try:
        return await svc.class_mastery(
            db, teacher.school_id, teacher.id, class_id, subject_id, chapter_id,
            lesson_id, from_date, to_date, locale,
        )
    except svc.InsightNotFound as error:
        raise _not_found() from error
    except svc.InsightValidationError as error:
        raise _invalid_dates() from error


@router.get("/students/{student_id}/mastery", response_model=StudentMasteryOut)
async def student_mastery(
    student_id: uuid.UUID,
    teacher: Teacher,
    db: DB,
    class_id: uuid.UUID = Query(),
    subject_id: str | None = Query(default=None, max_length=100),
    chapter_id: str | None = Query(default=None, max_length=100),
    lesson_id: str | None = Query(default=None, max_length=100),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    locale: Literal["en", "ar"] = Query(default="en"),
) -> StudentMasteryOut:
    try:
        return await svc.student_mastery(
            db, teacher.school_id, teacher.id, class_id, student_id, subject_id,
            chapter_id, lesson_id, from_date, to_date, locale,
        )
    except svc.InsightNotFound as error:
        raise _not_found() from error
    except svc.InsightValidationError as error:
        raise _invalid_dates() from error
