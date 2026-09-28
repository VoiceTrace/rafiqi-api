import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_teacher
from app.core.errors import ErrorCode
from app.schemas.class_group import (
    ClassGroupCreate,
    ClassGroupOut,
    ClassGroupUpdate,
    EnrolledStudentOut,
    EnrollmentCreate,
    EnrollmentOut,
)
from app.services import class_group as svc

router = APIRouter(prefix="/teacher/classes", tags=["teacher classes"])
Teacher = Annotated[CurrentUser, Depends(require_teacher)]
DB = Annotated[AsyncSession, Depends(get_db_session)]


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": ErrorCode.NOT_FOUND, "message": message}},
    )


def _conflict(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": {"code": ErrorCode.CONFLICT, "message": message}},
    )


@router.get("", response_model=list[ClassGroupOut])
async def list_classes(
    teacher: Teacher,
    db: DB,
    active_only: bool = Query(default=True),
) -> list[ClassGroupOut]:
    return await svc.list_classes(db, teacher.school_id, teacher.id, active_only)


@router.post("", response_model=ClassGroupOut, status_code=status.HTTP_201_CREATED)
async def create_class(body: ClassGroupCreate, teacher: Teacher, db: DB) -> ClassGroupOut:
    try:
        return await svc.create_class(db, teacher.school_id, teacher.id, body)
    except svc.SubjectNotFound as error:
        raise _not_found("Subject not found") from error
    except svc.ClassGroupConflict as error:
        raise _conflict("A class with this name and academic year already exists") from error


@router.get("/{class_id}", response_model=ClassGroupOut)
async def get_class(class_id: uuid.UUID, teacher: Teacher, db: DB) -> ClassGroupOut:
    try:
        return await svc.get_class(db, teacher.school_id, teacher.id, class_id)
    except svc.ClassGroupNotFound as error:
        raise _not_found("Class not found") from error


@router.patch("/{class_id}", response_model=ClassGroupOut)
async def update_class(
    class_id: uuid.UUID, body: ClassGroupUpdate, teacher: Teacher, db: DB
) -> ClassGroupOut:
    try:
        return await svc.update_class(db, teacher.school_id, teacher.id, class_id, body)
    except svc.ClassGroupNotFound as error:
        raise _not_found("Class not found") from error
    except svc.SubjectNotFound as error:
        raise _not_found("Subject not found") from error
    except svc.ClassGroupConflict as error:
        raise _conflict("A class with this name and academic year already exists") from error


@router.get("/{class_id}/students", response_model=list[EnrolledStudentOut])
async def list_students(
    class_id: uuid.UUID, teacher: Teacher, db: DB
) -> list[EnrolledStudentOut]:
    try:
        return await svc.list_students(db, teacher.school_id, teacher.id, class_id)
    except svc.ClassGroupNotFound as error:
        raise _not_found("Class not found") from error


@router.post(
    "/{class_id}/students",
    response_model=EnrollmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def enroll_student(
    class_id: uuid.UUID, body: EnrollmentCreate, teacher: Teacher, db: DB
) -> EnrollmentOut:
    try:
        return await svc.enroll_student(
            db, teacher.school_id, teacher.id, class_id, body.student_id
        )
    except svc.ClassGroupNotFound as error:
        raise _not_found("Class not found") from error
    except svc.StudentNotFound as error:
        raise _not_found("Student not found") from error
    except svc.ClassGroupConflict as error:
        raise _conflict("Student is already enrolled") from error


@router.delete("/{class_id}/students/{student_id}", response_model=EnrollmentOut)
async def remove_student(
    class_id: uuid.UUID, student_id: uuid.UUID, teacher: Teacher, db: DB
) -> EnrollmentOut:
    try:
        return await svc.remove_student(
            db, teacher.school_id, teacher.id, class_id, student_id
        )
    except svc.ClassGroupNotFound as error:
        raise _not_found("Class not found") from error
    except svc.StudentNotFound as error:
        raise _not_found("Active enrollment not found") from error
