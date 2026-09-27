import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.class_group import ClassEnrollment, ClassGroup
from app.models.review import ReviewSubject
from app.models.user import User, UserRole
from app.schemas.class_group import (
    ClassGroupCreate,
    ClassGroupOut,
    ClassGroupUpdate,
    EnrolledStudentOut,
    EnrollmentOut,
)


class ClassGroupNotFound(Exception):
    pass


class StudentNotFound(Exception):
    pass


class SubjectNotFound(Exception):
    pass


class ClassGroupConflict(Exception):
    pass


async def _owned_class(
    db: AsyncSession, school_id: uuid.UUID, teacher_id: uuid.UUID, class_id: uuid.UUID
) -> ClassGroup:
    row = await db.scalar(
        select(ClassGroup).where(
            ClassGroup.id == class_id,
            ClassGroup.school_id == school_id,
            ClassGroup.teacher_id == teacher_id,
        )
    )
    if row is None:
        raise ClassGroupNotFound(class_id)
    return row


def _class_out(row: ClassGroup, student_count: int = 0) -> ClassGroupOut:
    return ClassGroupOut(
        id=row.id,
        school_id=row.school_id,
        teacher_id=row.teacher_id,
        name=row.name,
        grade_level=row.grade_level,
        subject_id=row.subject_id,
        academic_year=row.academic_year,
        is_active=row.is_active,
        student_count=student_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_classes(
    db: AsyncSession, school_id: uuid.UUID, teacher_id: uuid.UUID, active_only: bool
) -> list[ClassGroupOut]:
    counts = (
        select(
            ClassEnrollment.class_group_id,
            func.count(ClassEnrollment.id).label("student_count"),
        )
        .where(ClassEnrollment.school_id == school_id, ClassEnrollment.is_active.is_(True))
        .group_by(ClassEnrollment.class_group_id)
        .subquery()
    )
    query = (
        select(ClassGroup, func.coalesce(counts.c.student_count, 0))
        .outerjoin(counts, counts.c.class_group_id == ClassGroup.id)
        .where(ClassGroup.school_id == school_id, ClassGroup.teacher_id == teacher_id)
        .order_by(ClassGroup.name, ClassGroup.id)
    )
    if active_only:
        query = query.where(ClassGroup.is_active.is_(True))
    rows = (await db.execute(query)).all()
    return [_class_out(group, int(count)) for group, count in rows]


async def get_class(
    db: AsyncSession, school_id: uuid.UUID, teacher_id: uuid.UUID, class_id: uuid.UUID
) -> ClassGroupOut:
    group = await _owned_class(db, school_id, teacher_id, class_id)
    count = await db.scalar(
        select(func.count(ClassEnrollment.id)).where(
            ClassEnrollment.school_id == school_id,
            ClassEnrollment.class_group_id == class_id,
            ClassEnrollment.is_active.is_(True),
        )
    )
    return _class_out(group, int(count or 0))


async def create_class(
    db: AsyncSession,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    req: ClassGroupCreate,
) -> ClassGroupOut:
    if await db.scalar(select(ReviewSubject.id).where(ReviewSubject.id == req.subject_id)) is None:
        raise SubjectNotFound(req.subject_id)
    group = ClassGroup(
        school_id=school_id,
        teacher_id=teacher_id,
        name=req.name,
        grade_level=req.grade_level,
        subject_id=req.subject_id,
        academic_year=req.academic_year,
    )
    db.add(group)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ClassGroupConflict() from error
    await db.refresh(group)
    return _class_out(group)


async def update_class(
    db: AsyncSession,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    req: ClassGroupUpdate,
) -> ClassGroupOut:
    group = await _owned_class(db, school_id, teacher_id, class_id)
    changes = req.model_dump(exclude_unset=True)
    subject_id = changes.get("subject_id")
    if subject_id is not None and await db.scalar(
        select(ReviewSubject.id).where(ReviewSubject.id == subject_id)
    ) is None:
        raise SubjectNotFound(subject_id)
    for field, value in changes.items():
        setattr(group, field, value)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ClassGroupConflict() from error
    await db.refresh(group)
    return await get_class(db, school_id, teacher_id, class_id)


async def list_students(
    db: AsyncSession, school_id: uuid.UUID, teacher_id: uuid.UUID, class_id: uuid.UUID
) -> list[EnrolledStudentOut]:
    await _owned_class(db, school_id, teacher_id, class_id)
    rows = (
        await db.execute(
            select(User, ClassEnrollment)
            .join(ClassEnrollment, ClassEnrollment.student_id == User.id)
            .where(
                ClassEnrollment.school_id == school_id,
                ClassEnrollment.class_group_id == class_id,
                ClassEnrollment.is_active.is_(True),
                User.school_id == school_id,
                User.role == UserRole.STUDENT,
                User.is_active.is_(True),
            )
            .order_by(User.full_name, User.id)
        )
    ).all()
    return [
        EnrolledStudentOut(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            avatar_url=user.avatar_url,
            is_active=user.is_active,
            enrollment_id=enrollment.id,
            enrolled_at=enrollment.enrolled_at,
        )
        for user, enrollment in rows
    ]


async def enroll_student(
    db: AsyncSession,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    student_id: uuid.UUID,
) -> EnrollmentOut:
    await _owned_class(db, school_id, teacher_id, class_id)
    student = await db.scalar(
        select(User).where(
            User.id == student_id,
            User.school_id == school_id,
            User.role == UserRole.STUDENT,
            User.is_active.is_(True),
        )
    )
    if student is None:
        raise StudentNotFound(student_id)
    enrollment = await db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.school_id == school_id,
            ClassEnrollment.class_group_id == class_id,
            ClassEnrollment.student_id == student_id,
        )
    )
    if enrollment is None:
        enrollment = ClassEnrollment(
            school_id=school_id, class_group_id=class_id, student_id=student_id
        )
        db.add(enrollment)
    elif enrollment.is_active:
        raise ClassGroupConflict()
    else:
        enrollment.is_active = True
    await db.commit()
    await db.refresh(enrollment)
    return EnrollmentOut.model_validate(enrollment)


async def remove_student(
    db: AsyncSession,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    student_id: uuid.UUID,
) -> EnrollmentOut:
    await _owned_class(db, school_id, teacher_id, class_id)
    enrollment = await db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.school_id == school_id,
            ClassEnrollment.class_group_id == class_id,
            ClassEnrollment.student_id == student_id,
            ClassEnrollment.is_active.is_(True),
        )
    )
    if enrollment is None:
        raise StudentNotFound(student_id)
    enrollment.is_active = False
    await db.commit()
    await db.refresh(enrollment)
    return EnrollmentOut.model_validate(enrollment)
