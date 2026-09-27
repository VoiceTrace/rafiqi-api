import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.class_group import ClassEnrollment, ClassGroup
from app.models.review import ReviewAttempt, ReviewChapter, ReviewLesson, ReviewSessionSummary
from app.models.user import User, UserRole
from app.schemas.teacher_insights import (
    ClassMasteryOut,
    ConceptMasteryOut,
    MasteryBandCounts,
    MasteryFilterOut,
    StudentMasteryOut,
    StudentMasteryRow,
    ClassMisconceptionsOut,
    MisconceptionOut,
    ReviewConceptOutcome,
    ReviewSessionPage,
    TeacherAttemptEvidence,
    TeacherReviewSessionDetail,
    TeacherReviewSessionItem,
)
from app.services.review import mastery_band

Locale = Literal["en", "ar"]


class InsightNotFound(Exception):
    pass


class InsightValidationError(Exception):
    pass


_ERROR_LABELS = {
    "force_pair_unequal_magnitude": {
        "en": "Treats the force pair as unequal in magnitude",
        "ar": "يعتقد أن قوتي الفعل ورد الفعل غير متساويتين",
    },
    "force_pair_missing_reaction": {
        "en": "Does not identify the reaction force",
        "ar": "لا يحدد قوة رد الفعل",
    },
    "force_pair_incomplete_distinct_objects": {
        "en": "Partly identifies that the forces act on different objects",
        "ar": "يحدد جزئياً أن القوتين تؤثران في جسمين مختلفين",
    },
    "force_pair_missing_distinct_objects": {
        "en": "Does not identify that the forces act on different objects",
        "ar": "لا يحدد أن القوتين تؤثران في جسمين مختلفين",
    },
    "balanced_force_means_stopped": {
        "en": "Assumes balanced forces mean an object must be stopped",
        "ar": "يفترض أن اتزان القوى يعني أن الجسم متوقف",
    },
    "kinetic_energy_requires_motion": {
        "en": "Does not connect kinetic energy with motion",
        "ar": "لا يربط الطاقة الحركية بالحركة",
    },
    "equivalent_fraction_denominator_only": {
        "en": "Changes only the denominator when forming an equivalent fraction",
        "ar": "يغير المقام فقط عند تكوين كسر مكافئ",
    },
}


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


def _session_concepts(summary: ReviewSessionSummary, content: dict, locale: Locale) -> list[ReviewConceptOutcome]:
    return [
        ReviewConceptOutcome(
            concept_ref=item["concept_ref"],
            title=_concept_title(content, locale, item["concept_ref"]),
            outcome=item["outcome"],
            completed_with_support=bool(item.get("completed_with_support", False)),
        )
        for item in summary.concepts
    ]


async def _session_rows(
    db: AsyncSession,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: str,
    chapter_id: str | None,
    lesson_id: str | None,
    from_date: date | None,
    to_date: date | None,
    student_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
):
    start, end = _date_bounds(from_date, to_date)
    query = (
        select(ReviewSessionSummary, User.full_name, ReviewLesson.content, ReviewLesson.chapter_id)
        .join(ClassEnrollment, ClassEnrollment.student_id == ReviewSessionSummary.student_id)
        .join(User, User.id == ReviewSessionSummary.student_id)
        .join(ReviewLesson, ReviewLesson.id == ReviewSessionSummary.lesson_id)
        .join(ReviewChapter, ReviewChapter.id == ReviewLesson.chapter_id)
        .where(
            ReviewSessionSummary.school_id == school_id,
            ClassEnrollment.school_id == school_id,
            ClassEnrollment.class_group_id == class_id,
            ClassEnrollment.is_active.is_(True),
            User.school_id == school_id,
            User.role == UserRole.STUDENT,
            User.is_active.is_(True),
            ReviewChapter.subject_id == subject_id,
        )
        .order_by(ReviewSessionSummary.completed_at.desc(), ReviewSessionSummary.session_id)
    )
    if chapter_id:
        query = query.where(ReviewLesson.chapter_id == chapter_id)
    if lesson_id:
        query = query.where(ReviewSessionSummary.lesson_id == lesson_id)
    if student_id:
        query = query.where(ReviewSessionSummary.student_id == student_id)
    if session_id:
        query = query.where(ReviewSessionSummary.session_id == session_id)
    if start:
        query = query.where(ReviewSessionSummary.completed_at >= start)
    if end:
        query = query.where(ReviewSessionSummary.completed_at < end)
    return (await db.execute(query)).all()


async def _dominant_errors(
    db: AsyncSession, school_id: uuid.UUID, session_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    if not session_ids:
        return {}
    attempts = (
        await db.execute(
            select(ReviewAttempt.session_id, ReviewAttempt.error_type)
            .where(
                ReviewAttempt.school_id == school_id,
                ReviewAttempt.session_id.in_(session_ids),
                ReviewAttempt.error_type.is_not(None),
            )
            .order_by(ReviewAttempt.created_at, ReviewAttempt.id)
        )
    ).all()
    counts = defaultdict(Counter)
    for session_id, error_type in attempts:
        counts[session_id][error_type] += 1
    return {
        session_id: (counter.most_common(1)[0][0] if counter else None)
        for session_id, counter in counts.items()
    }


async def review_sessions(
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
    page: int,
    page_size: int,
    student_id: uuid.UUID | None = None,
    mastery_outcome: str | None = None,
) -> ReviewSessionPage:
    group = await _owned_class(db, school_id, teacher_id, class_id)
    selected_subject = subject_id or group.subject_id
    if student_id is not None and await db.scalar(
        select(ClassEnrollment.id)
        .join(User, User.id == ClassEnrollment.student_id)
        .where(
            ClassEnrollment.school_id == school_id,
            ClassEnrollment.class_group_id == class_id,
            ClassEnrollment.student_id == student_id,
            ClassEnrollment.is_active.is_(True),
            User.school_id == school_id,
            User.role == UserRole.STUDENT,
            User.is_active.is_(True),
        )
    ) is None:
        raise InsightNotFound()
    rows = await _session_rows(
        db, school_id, class_id, selected_subject, chapter_id, lesson_id,
        from_date, to_date, student_id=student_id,
    )
    if mastery_outcome:
        rows = [row for row in rows if any(item.get("outcome") == mastery_outcome for item in row[0].concepts)]
    total = len(rows)
    rows = rows[(page - 1) * page_size:page * page_size]
    errors = await _dominant_errors(db, school_id, [row[0].session_id for row in rows])
    items = [
        TeacherReviewSessionItem(
            session_id=summary.session_id,
            student_id=summary.student_id,
            student_name=student_name,
            lesson_id=summary.lesson_id,
            lesson_title=(content.get(locale) or content.get("en") or {}).get("title", summary.lesson_id),
            subject_id=selected_subject,
            chapter_id=row_chapter_id,
            concepts=_session_concepts(summary, content, locale),
            total_attempts=summary.total_attempts,
            dominant_error_type=errors.get(summary.session_id),
            completed_at=summary.completed_at,
        )
        for summary, student_name, content, row_chapter_id in rows
    ]
    return ReviewSessionPage(items=items, total=total, page=page, page_size=page_size)


async def review_session_detail(
    db: AsyncSession,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    session_id: uuid.UUID,
    locale: Locale,
) -> TeacherReviewSessionDetail:
    group = await _owned_class(db, school_id, teacher_id, class_id)
    rows = await _session_rows(
        db, school_id, class_id, group.subject_id, None, None, None, None,
        session_id=session_id,
    )
    if not rows:
        raise InsightNotFound()
    summary, student_name, content, chapter_id = rows[0]
    attempts = list(
        (
            await db.scalars(
                select(ReviewAttempt)
                .where(
                    ReviewAttempt.school_id == school_id,
                    ReviewAttempt.student_id == summary.student_id,
                    ReviewAttempt.session_id == session_id,
                )
                .order_by(ReviewAttempt.created_at, ReviewAttempt.attempt_number, ReviewAttempt.id)
            )
        ).all()
    )
    errors = Counter(item.error_type for item in attempts if item.error_type)
    return TeacherReviewSessionDetail(
        session_id=summary.session_id,
        student_id=summary.student_id,
        student_name=student_name,
        lesson_id=summary.lesson_id,
        lesson_title=(content.get(locale) or content.get("en") or {}).get("title", summary.lesson_id),
        subject_id=group.subject_id,
        chapter_id=chapter_id,
        concepts=_session_concepts(summary, content, locale),
        total_attempts=summary.total_attempts,
        dominant_error_type=errors.most_common(1)[0][0] if errors else None,
        completed_at=summary.completed_at,
        attempts=[TeacherAttemptEvidence.model_validate(item, from_attributes=True) for item in attempts],
    )


async def class_misconceptions(
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
) -> ClassMisconceptionsOut:
    group = await _owned_class(db, school_id, teacher_id, class_id)
    selected_subject = subject_id or group.subject_id
    rows = await _evidence(
        db, school_id, class_id, selected_subject, chapter_id, lesson_id,
        from_date, to_date,
    )
    students_with_evidence = len({attempt.student_id for attempt, *_ in rows})
    grouped = defaultdict(list)
    for attempt, *_ in rows:
        if attempt.error_type:
            grouped[(attempt.error_type, attempt.concept_ref)].append(attempt)
    items = []
    for (error_type, concept_ref), attempts in grouped.items():
        student_count = len({item.student_id for item in attempts})
        labels = _ERROR_LABELS.get(error_type, {})
        items.append(
            MisconceptionOut(
                error_type=error_type,
                label=labels.get(locale) or labels.get("en") or error_type,
                concept_ref=concept_ref,
                student_count=student_count,
                attempt_count=len(attempts),
                students_with_evidence=students_with_evidence,
                percentage=(student_count / students_with_evidence * 100) if students_with_evidence else 0,
                lesson_ids=sorted({item.lesson_id for item in attempts}),
                last_occurred_at=max(item.created_at for item in attempts),
            )
        )
    items.sort(key=lambda item: (-item.student_count, -item.attempt_count, item.error_type))
    return ClassMisconceptionsOut(
        class_id=class_id,
        filters=MasteryFilterOut(
            subject_id=selected_subject,
            chapter_id=chapter_id,
            lesson_id=lesson_id,
            from_date=from_date,
            to_date=to_date,
            locale=locale,
        ),
        students_with_evidence=students_with_evidence,
        items=items,
    )
