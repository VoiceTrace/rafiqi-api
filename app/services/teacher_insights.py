import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.class_group import ClassEnrollment, ClassGroup
from app.models.review import ReviewAttempt, ReviewChapter, ReviewLesson
from app.models.user import User, UserRole
from app.schemas.teacher_insights import (
    ClassMasteryOut,
    ConceptMasteryOut,
    MasteryBandCounts,
    MasteryFilterOut,
    StudentMasteryOut,
    StudentMasteryRow,
)
from app.services.review import mastery_band

Locale = Literal["en", "ar"]


class InsightNotFound(Exception):
    pass


class InsightValidationError(Exception):
    pass


async def _owned_class(
    db: AsyncSession, school_id: uuid.UUID, teacher_id: uuid.UUID, class_id: uuid.UUID
) -> ClassGroup:
    group = await db.scalar(
        select(ClassGroup).where(
            ClassGroup.id == class_id,
            ClassGroup.school_id == school_id,
            ClassGroup.teacher_id == teacher_id,
            ClassGroup.is_active.is_(True),
        )
    )
    if group is None:
        raise InsightNotFound()
    return group


def _date_bounds(from_date: date | None, to_date: date | None) -> tuple[datetime | None, datetime | None]:
    if from_date and to_date and from_date > to_date:
        raise InsightValidationError()
    start = datetime.combine(from_date, time.min, tzinfo=timezone.utc) if from_date else None
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=timezone.utc) if to_date else None
    return start, end


def _concept_title(content: dict, locale: Locale, concept_ref: str) -> str:
    localized = content.get(locale) or content.get("en") or {}
    for concept in localized.get("concept_refs", []):
        if concept.get("id") == concept_ref:
            return concept.get("title") or concept_ref
    return concept_ref


async def _evidence(
    db: AsyncSession,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: str,
    chapter_id: str | None,
    lesson_id: str | None,
    from_date: date | None,
    to_date: date | None,
    student_id: uuid.UUID | None = None,
):
    start, end = _date_bounds(from_date, to_date)
    query = (
        select(ReviewAttempt, ReviewLesson.content, User.full_name, User.avatar_url)
        .join(ClassEnrollment, ClassEnrollment.student_id == ReviewAttempt.student_id)
        .join(User, User.id == ReviewAttempt.student_id)
        .join(ReviewLesson, ReviewLesson.id == ReviewAttempt.lesson_id)
        .join(ReviewChapter, ReviewChapter.id == ReviewLesson.chapter_id)
        .where(
            ReviewAttempt.school_id == school_id,
            ClassEnrollment.school_id == school_id,
            ClassEnrollment.class_group_id == class_id,
            ClassEnrollment.is_active.is_(True),
            User.school_id == school_id,
            User.role == UserRole.STUDENT,
            User.is_active.is_(True),
            ReviewChapter.subject_id == subject_id,
        )
        .order_by(
            ReviewAttempt.created_at,
            ReviewAttempt.attempt_number,
            ReviewAttempt.id,
        )
    )
    if chapter_id:
        query = query.where(ReviewLesson.chapter_id == chapter_id)
    if lesson_id:
        query = query.where(ReviewAttempt.lesson_id == lesson_id)
    if student_id:
        query = query.where(ReviewAttempt.student_id == student_id)
    if start:
        query = query.where(ReviewAttempt.created_at >= start)
    if end:
        query = query.where(ReviewAttempt.created_at < end)
    return (await db.execute(query)).all()


def _summaries(rows, locale: Locale):
    all_attempts = defaultdict(list)
    latest = {}
    identities = {}
    titles = {}
    for attempt, content, full_name, avatar_url in rows:
        key = (attempt.student_id, attempt.lesson_id, attempt.question_id)
        latest[key] = attempt
        all_attempts[(attempt.student_id, attempt.concept_ref)].append(attempt)
        identities[attempt.student_id] = (full_name, avatar_url)
        titles.setdefault(attempt.concept_ref, _concept_title(content, locale, attempt.concept_ref))

    concept_evidence = defaultdict(list)
    for attempt in latest.values():
        concept_evidence[(attempt.student_id, attempt.concept_ref)].append(attempt)

    student_concepts = defaultdict(list)
    concept_students = defaultdict(list)
    for (student_id, concept_ref), evidence in concept_evidence.items():
        attempts = all_attempts[(student_id, concept_ref)]
        score = sum(item.correctness_score for item in evidence) / len(evidence)
        errors = Counter(item.error_type for item in attempts if item.error_type)
        summary = {
            "concept_ref": concept_ref,
            "title": titles.get(concept_ref, concept_ref),
            "score": score,
            "band": mastery_band(score),
            "evidence_count": len(evidence),
            "attempt_count": len(attempts),
            "assisted_count": sum(item.assisted for item in evidence),
            "dominant_error": errors.most_common(1)[0][0] if errors else None,
            "last_attempt": max(item.created_at for item in attempts),
        }
        student_concepts[student_id].append(summary)
        concept_students[concept_ref].append(summary)
    return identities, student_concepts, concept_students


def _concept_outputs(concept_students) -> list[ConceptMasteryOut]:
    outputs = []
    for concept_ref, summaries in concept_students.items():
        score = sum(item["score"] for item in summaries) / len(summaries)
        errors = Counter(item["dominant_error"] for item in summaries if item["dominant_error"])
        outputs.append(
            ConceptMasteryOut(
                concept_ref=concept_ref,
                title=summaries[0]["title"],
                mastery_score=score,
                mastery_band=mastery_band(score),
                student_count=len(summaries),
                evidence_count=sum(item["evidence_count"] for item in summaries),
                attempt_count=sum(item["attempt_count"] for item in summaries),
                assisted_evidence_count=sum(item["assisted_count"] for item in summaries),
                dominant_error_type=errors.most_common(1)[0][0] if errors else None,
                last_attempt_at=max(item["last_attempt"] for item in summaries),
            )
        )
    return sorted(outputs, key=lambda item: (item.mastery_score, item.concept_ref))


def _student_row(student_id, full_name, avatar_url, concepts) -> StudentMasteryRow:
    if not concepts:
        return StudentMasteryRow(
            student_id=student_id,
            full_name=full_name,
            avatar_url=avatar_url,
            concept_count=0,
            evidence_count=0,
            attempt_count=0,
            assisted_evidence_count=0,
            dominant_error_type=None,
            last_attempt_at=None,
        )
    score = sum(item["score"] for item in concepts) / len(concepts)
    errors = Counter(item["dominant_error"] for item in concepts if item["dominant_error"])
    return StudentMasteryRow(
        student_id=student_id,
        full_name=full_name,
        avatar_url=avatar_url,
        mastery_score=score,
        mastery_band=mastery_band(score),
        concept_count=len(concepts),
        evidence_count=sum(item["evidence_count"] for item in concepts),
        attempt_count=sum(item["attempt_count"] for item in concepts),
        assisted_evidence_count=sum(item["assisted_count"] for item in concepts),
        dominant_error_type=errors.most_common(1)[0][0] if errors else None,
        last_attempt_at=max(item["last_attempt"] for item in concepts),
    )


async def class_mastery(
    db: AsyncSession,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: str | None,
    chapter_id: str | None,
    lesson_id: str | None,
    from_date: date | None,
    to_date: date | None,
    locale: Locale,
) -> ClassMasteryOut:
    group = await _owned_class(db, school_id, teacher_id, class_id)
    selected_subject = subject_id or group.subject_id
    roster = (
        await db.execute(
            select(User.id, User.full_name, User.avatar_url)
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
    rows = await _evidence(
        db, school_id, class_id, selected_subject, chapter_id, lesson_id,
        from_date, to_date,
    )
    _, student_concepts, concept_students = _summaries(rows, locale)
    students = [_student_row(student_id, name, avatar, student_concepts[student_id]) for student_id, name, avatar in roster]
    bands = Counter(student.mastery_band or "no_evidence" for student in students)
    with_evidence = [student for student in students if student.mastery_score is not None]
    filters = MasteryFilterOut(
        subject_id=selected_subject,
        chapter_id=chapter_id,
        lesson_id=lesson_id,
        from_date=from_date,
        to_date=to_date,
        locale=locale,
    )
    return ClassMasteryOut(
        class_id=group.id,
        class_name=group.name,
        filters=filters,
        enrolled_student_count=len(students),
        students_with_evidence=len(with_evidence),
        average_mastery=(sum(item.mastery_score for item in with_evidence) / len(with_evidence)) if with_evidence else None,
        band_counts=MasteryBandCounts(
            needs_support=bands["needs_support"],
            developing=bands["developing"],
            secure=bands["secure"],
            no_evidence=bands["no_evidence"],
        ),
        students=students,
        concepts=_concept_outputs(concept_students),
    )


async def student_mastery(
    db: AsyncSession,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    student_id: uuid.UUID,
    subject_id: str | None,
    chapter_id: str | None,
    lesson_id: str | None,
    from_date: date | None,
    to_date: date | None,
    locale: Locale,
) -> StudentMasteryOut:
    group = await _owned_class(db, school_id, teacher_id, class_id)
    student = (
        await db.execute(
            select(User.id, User.full_name, User.avatar_url)
            .join(ClassEnrollment, ClassEnrollment.student_id == User.id)
            .where(
                User.id == student_id,
                User.school_id == school_id,
                User.role == UserRole.STUDENT,
                User.is_active.is_(True),
                ClassEnrollment.school_id == school_id,
                ClassEnrollment.class_group_id == class_id,
                ClassEnrollment.is_active.is_(True),
            )
        )
    ).one_or_none()
    if student is None:
        raise InsightNotFound()
    selected_subject = subject_id or group.subject_id
    rows = await _evidence(
        db, school_id, class_id, selected_subject, chapter_id, lesson_id,
        from_date, to_date, student_id,
    )
    _, student_concepts, concept_students = _summaries(rows, locale)
    row = _student_row(student.id, student.full_name, student.avatar_url, student_concepts[student.id])
    return StudentMasteryOut(
        class_id=group.id,
        student=row,
        filters=MasteryFilterOut(
            subject_id=selected_subject,
            chapter_id=chapter_id,
            lesson_id=lesson_id,
            from_date=from_date,
            to_date=to_date,
            locale=locale,
        ),
        concepts=_concept_outputs(concept_students),
    )
