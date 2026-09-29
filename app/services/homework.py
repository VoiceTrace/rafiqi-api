"""Epic E — Homework service layer.

v1: teacher creates fixed MCQ questions; same set distributed to all students.

RAFIQI_V2: Search for "RAFIQI_V2" comments to find the generation scaffold.
Uncomment those blocks to activate AI-generated personalized homework sets.

PARENT_V2: Search for "PARENT_V2" comments to find the parent-delivery scaffold.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ErrorCode
from app.models.user import User, UserRole
from app.models.homework import (
    AssignmentStatus,
    HomeworkAssignment,
    HomeworkAttempt,
    HomeworkHintReveal,
    HomeworkQuestion,
    StudentAssignment,
    StudentAssignmentStatus,
)
from app.models.study_session import MasteryRecord
from app.schemas.homework import (
    AddQuestionRequest,
    AnswerInput,
    AssignmentRead,
    AssignmentWithQuestions,
    AttemptResult,
    ConceptGap,
    CreateAssignmentRequest,
    DistributeRequest,
    GradeSubmissionRequest,
    GapDigestRead,
    MCQOption,
    HintRevealRead,
    QuestionRead,
    QuestionReadTeacher,
    StudentAssignmentRead,
    StudentAssignmentWithQuestions,
    SubmissionResult,
    TeacherAttemptRead,
    TeacherSubmissionRead,
    UpdateAssignmentRequest,
    UpdateQuestionRequest,
)

# THRESHOLD: correctness threshold for a homework answer to be considered "correct".
# Will be made configurable per assignment / year group in v2.
CORRECT_THRESHOLD = 0.8

# Minimum student coverage to present gap digest as reliable class-level data.
# Below this, the digest is shown with a low-coverage warning.
GAP_DIGEST_COVERAGE_THRESHOLD = 0.5  # 50 % of distributed students

# RAFIQI_V2: When differentiated generation is active, minimum number of
# MasteryRecord entries required per student before personalization kicks in.
# RAFIQI_MIN_MASTERY_RECORDS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _not_found(msg: str = "Not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": {"code": ErrorCode.NOT_FOUND, "message": msg}})


def _forbidden(msg: str = "Forbidden") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": {"code": ErrorCode.FORBIDDEN, "message": msg}})


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": {"code": ErrorCode.CONFLICT, "message": msg}})


def _bad_request(msg: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": {"code": ErrorCode.VALIDATION_ERROR, "message": msg}})


def _assignment_to_read(a: HomeworkAssignment, question_count: int | None = None) -> AssignmentRead:
    # question_count must be passed explicitly when calling after commit() — accessing
    # a.questions after commit triggers a lazy load in sync context (MissingGreenlet).
    if question_count is None:
        question_count = len(a.questions) if a.questions else 0
    return AssignmentRead(
        id=a.id,
        school_id=a.school_id,
        teacher_id=a.teacher_id,
        grade_level=a.grade_level,
        subject=a.subject,
        chapter=a.chapter,
        lesson_id=a.lesson_id,
        title=a.title,
        description=a.description,
        status=a.status,
        due_at=a.due_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
        question_count=question_count,
    )


def _question_to_teacher_read(q: HomeworkQuestion) -> QuestionReadTeacher:
    return QuestionReadTeacher(
        id=q.id,
        assignment_id=q.assignment_id,
        question_text=q.question_text,
        format=q.format,
        options=[MCQOption(id=o["id"], text=o["text"]) for o in q.options],
        concept_ref=q.concept_ref,
        hints=q.hints,
        order=q.order,
        correct_answer=q.correct_answer,
    )


def _question_to_student_read(q: HomeworkQuestion, revealed_hint_count: int = 0) -> QuestionRead:
    return QuestionRead(
        id=q.id,
        assignment_id=q.assignment_id,
        question_text=q.question_text,
        format=q.format,
        options=[MCQOption(id=o["id"], text=o["text"]) for o in q.options],
        concept_ref=q.concept_ref,
        hint_count=len(q.hints),
        revealed_hint_count=revealed_hint_count,
        order=q.order,
    )


def _mastery_confidence(score: float) -> str:
    if score < 0.4:
        return "forming"
    if score < 0.75:
        return "developing"
    return "solid"


# ── Teacher: assignment CRUD ──────────────────────────────────────────────────

async def create_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    req: CreateAssignmentRequest,
) -> AssignmentRead:
    a = HomeworkAssignment(
        school_id=school_id,
        teacher_id=teacher_id,
        grade_level=req.grade_level,
        subject=req.subject,
        chapter=req.chapter,
        lesson_id=req.lesson_id,
        title=req.title,
        description=req.description,
        due_at=req.due_at,
        status=AssignmentStatus.draft,
    )
    db.add(a)
    await db.flush()
    await db.commit()
    await db.refresh(a)
    # Do not access a.questions here — refresh expires relationships and
    # touching the collection triggers a lazy load outside async context.
    return AssignmentRead(
        id=a.id,
        school_id=a.school_id,
        teacher_id=a.teacher_id,
        subject=a.subject,
        chapter=a.chapter,
        lesson_id=a.lesson_id,
        title=a.title,
        description=a.description,
        status=a.status,
        due_at=a.due_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
        question_count=0,
    )


async def list_assignments(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    lesson_id: str | None = None,
) -> list[AssignmentRead]:
    stmt = (
        select(HomeworkAssignment)
        .where(
            HomeworkAssignment.teacher_id == teacher_id,
            HomeworkAssignment.school_id == school_id,
        )
        .options(selectinload(HomeworkAssignment.questions))
        .order_by(HomeworkAssignment.created_at.desc())
    )
    if lesson_id:
        stmt = stmt.where(HomeworkAssignment.lesson_id == lesson_id)
    result = await db.execute(stmt)
    return [_assignment_to_read(a) for a in result.scalars().all()]


async def get_assignment_teacher(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> AssignmentWithQuestions:
    stmt = (
        select(HomeworkAssignment)
        .where(
            HomeworkAssignment.id == assignment_id,
            HomeworkAssignment.school_id == school_id,
        )
        .options(selectinload(HomeworkAssignment.questions))
    )
    result = await db.execute(stmt)
    a = result.scalar_one_or_none()
    if a is None:
        raise _not_found("Assignment not found")
    if a.teacher_id != teacher_id:
        raise _forbidden("This assignment belongs to another teacher")
    return AssignmentWithQuestions(
        **_assignment_to_read(a).model_dump(),
        questions=[_question_to_teacher_read(q) for q in a.questions],
    )


async def update_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
    req: UpdateAssignmentRequest,
) -> AssignmentRead:
    stmt = (
        select(HomeworkAssignment)
        .where(HomeworkAssignment.id == assignment_id, HomeworkAssignment.school_id == school_id)
        .options(selectinload(HomeworkAssignment.questions))
        .with_for_update()
    )
    result = await db.execute(stmt)
    a = result.scalar_one_or_none()
    if a is None:
        raise _not_found("Assignment not found")
    if a.teacher_id != teacher_id:
        raise _forbidden()
    if a.status != AssignmentStatus.draft:
        raise _conflict("Only draft assignments can be edited")
    if req.subject is not None:
        a.subject = req.subject
    if req.grade_level is not None:
        a.grade_level = req.grade_level
    if req.chapter is not None:
        a.chapter = req.chapter
    if req.lesson_id is not None:
        a.lesson_id = req.lesson_id
    if req.title is not None:
        a.title = req.title
    if "description" in req.model_fields_set:
        a.description = req.description
    if "due_at" in req.model_fields_set:
        a.due_at = req.due_at
    q_count = len(a.questions) if a.questions else 0
    await db.flush()
    await db.commit()
    await db.refresh(a)
    return _assignment_to_read(a, question_count=q_count)


async def delete_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> None:
    stmt = select(HomeworkAssignment).where(
        HomeworkAssignment.id == assignment_id,
        HomeworkAssignment.school_id == school_id,
    ).with_for_update()
    result = await db.execute(stmt)
    a = result.scalar_one_or_none()
    if a is None:
        raise _not_found()
    if a.teacher_id != teacher_id:
        raise _forbidden()
    if a.status != AssignmentStatus.draft:
        raise _conflict("Only draft assignments can be deleted")
    await db.delete(a)
    await db.commit()


# ── Teacher: question CRUD ────────────────────────────────────────────────────

async def _load_assignment_for_teacher(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    lock: bool = False,
) -> HomeworkAssignment:
    stmt = (
        select(HomeworkAssignment)
        .where(HomeworkAssignment.id == assignment_id, HomeworkAssignment.school_id == school_id)
        .options(selectinload(HomeworkAssignment.questions))
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    a = result.scalar_one_or_none()
    if a is None:
        raise _not_found("Assignment not found")
    if a.teacher_id != teacher_id:
        raise _forbidden()
    return a


async def add_question(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
    req: AddQuestionRequest,
) -> QuestionReadTeacher:
    a = await _load_assignment_for_teacher(db, teacher_id, school_id, assignment_id, lock=True)
    if a.status != AssignmentStatus.draft:
        raise _conflict("Only draft assignments can have questions added")
    q = HomeworkQuestion(
        school_id=school_id,
        assignment_id=assignment_id,
        question_text=req.question_text,
        format=req.format,
        options=[o.model_dump() for o in req.options],
        correct_answer=req.correct_answer,
        hints=req.hints,
        concept_ref=req.concept_ref,
        order=req.order,
    )
    db.add(q)
    await db.flush()
    await db.commit()
    await db.refresh(q)
    return _question_to_teacher_read(q)


async def update_question(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
    req: UpdateQuestionRequest,
) -> QuestionReadTeacher:
    a = await _load_assignment_for_teacher(db, teacher_id, school_id, assignment_id, lock=True)
    if a.status != AssignmentStatus.draft:
        raise _conflict("Only draft assignment questions can be edited")
    stmt = select(HomeworkQuestion).where(
        HomeworkQuestion.id == question_id,
        HomeworkQuestion.assignment_id == assignment_id,
        HomeworkQuestion.school_id == school_id,
    )
    result = await db.execute(stmt)
    q = result.scalar_one_or_none()
    if q is None:
        raise _not_found("Question not found")
    # Validate the merged question before mutation, including options-only patches.
    question_format = req.format if req.format is not None else q.format
    options = [o.model_dump() for o in req.options] if req.options is not None else q.options
    correct_answer = req.correct_answer if req.correct_answer is not None else q.correct_answer
    try:
        AddQuestionRequest(
            question_text=req.question_text or q.question_text,
            format=question_format,
            options=[MCQOption(**option) for option in options],
            correct_answer=correct_answer,
            hints=req.hints if req.hints is not None else q.hints,
            concept_ref=req.concept_ref if "concept_ref" in req.model_fields_set else q.concept_ref,
            order=req.order if req.order is not None else q.order,
        )
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc
    if req.question_text is not None:
        q.question_text = req.question_text
    if req.options is not None:
        q.options = options
    if req.format is not None:
        q.format = req.format
    if req.correct_answer is not None:
        q.correct_answer = req.correct_answer
    if req.hints is not None:
        q.hints = req.hints
    if "concept_ref" in req.model_fields_set:
        q.concept_ref = req.concept_ref
    if req.order is not None:
        q.order = req.order
    await db.flush()
    await db.commit()
    return _question_to_teacher_read(q)


async def delete_question(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
) -> None:
    a = await _load_assignment_for_teacher(db, teacher_id, school_id, assignment_id, lock=True)
    if a.status != AssignmentStatus.draft:
        raise _conflict("Only draft assignment questions can be deleted")
    stmt = select(HomeworkQuestion).where(
        HomeworkQuestion.id == question_id,
        HomeworkQuestion.assignment_id == assignment_id,
        HomeworkQuestion.school_id == school_id,
    )
    result = await db.execute(stmt)
    q = result.scalar_one_or_none()
    if q is None:
        raise _not_found("Question not found")
    await db.delete(q)
    await db.commit()


# ── Teacher: distribute ───────────────────────────────────────────────────────

async def distribute_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
    req: DistributeRequest,
) -> AssignmentRead:
    a = await _load_assignment_for_teacher(db, teacher_id, school_id, assignment_id, lock=True)
    if a.status != AssignmentStatus.draft:
        raise _conflict("Only draft assignments can be distributed")
    if not a.questions:
        raise _conflict("Cannot distribute an assignment with no questions")
    if any(len(question.hints) > 3 for question in a.questions):
        raise _conflict("Questions can have at most 3 hints")

    recipients = await db.execute(select(User.id).where(
        User.school_id == school_id,
        User.role == UserRole.STUDENT,
        User.is_active.is_(True),
        User.grade_level == a.grade_level,
    ))
    recipient_ids = recipients.scalars().all()
    if not recipient_ids:
        raise _conflict("There are no active students in this grade")

    if req.due_at:
        a.due_at = req.due_at

    # RAFIQI_V2: When is_differentiated=True, generate per-student question sets here
    # instead of assigning the same questions to all students:
    #
    # for student_id in req.student_ids:
    #     mastery = await _load_mastery_for_student(db, school_id, student_id, a.lesson_id)
    #     if len(mastery) >= RAFIQI_MIN_MASTERY_RECORDS:
    #         generated_questions = await rafiqi.generate_homework(
    #             concepts=[m.concept_ref for m in mastery if m.mastery_score < 0.75],
    #             format="mcq",
    #         )
    #         # persist generated questions as HomeworkQuestion rows linked to a per-student copy
    #     else:
    #         # fall back to teacher-created questions
    #         pass

    for student_id in recipient_ids:
        sa = StudentAssignment(
            school_id=school_id,
            student_id=student_id,
            assignment_id=assignment_id,
            status=StudentAssignmentStatus.assigned,
        )
        db.add(sa)

    a.status = AssignmentStatus.distributed
    q_count = len(a.questions) if a.questions else 0
    await db.flush()
    await db.commit()
    await db.refresh(a)
    return _assignment_to_read(a, question_count=q_count)


def _teacher_submission_read(sa: StudentAssignment, student: User) -> TeacherSubmissionRead:
    revealed_by_question: dict[uuid.UUID, int] = {}
    for reveal in sa.hint_reveals:
        revealed_by_question[reveal.question_id] = revealed_by_question.get(reveal.question_id, 0) + 1
    attempts = sorted(sa.attempts, key=lambda attempt: (attempt.question.order, str(attempt.question_id)))
    return TeacherSubmissionRead(
        student_assignment_id=sa.id, student_id=sa.student_id, student_name=student.full_name,
        status=sa.status, score=sa.score, submitted_at=sa.submitted_at, approved_at=sa.approved_at,
        attempts=[TeacherAttemptRead(
            question_id=attempt.question_id, question_text=attempt.question.question_text,
            format=attempt.question.format, answer=attempt.student_answer,
            correct_answer=attempt.question.correct_answer,
            hints_revealed=revealed_by_question.get(attempt.question_id, 0),
            teacher_score=attempt.teacher_score, teacher_comment=attempt.teacher_comment,
        ) for attempt in attempts],
    )


async def list_submissions(
    db: AsyncSession, teacher_id: uuid.UUID, school_id: uuid.UUID, assignment_id: uuid.UUID,
) -> list[TeacherSubmissionRead]:
    await _load_assignment_for_teacher(db, teacher_id, school_id, assignment_id)
    result = await db.execute(
        select(StudentAssignment, User).join(User, User.id == StudentAssignment.student_id).where(
            StudentAssignment.assignment_id == assignment_id, StudentAssignment.school_id == school_id,
        ).options(
            selectinload(StudentAssignment.attempts).selectinload(HomeworkAttempt.question),
            selectinload(StudentAssignment.hint_reveals),
        ).order_by(User.full_name)
    )
    return [_teacher_submission_read(sa, student) for sa, student in result.all()]


async def grade_submission(
    db: AsyncSession, teacher_id: uuid.UUID, school_id: uuid.UUID, assignment_id: uuid.UUID,
    student_assignment_id: uuid.UUID, req: GradeSubmissionRequest,
) -> TeacherSubmissionRead:
    await _load_assignment_for_teacher(db, teacher_id, school_id, assignment_id)
    result = await db.execute(
        select(StudentAssignment, User).join(User, User.id == StudentAssignment.student_id).where(
            StudentAssignment.id == student_assignment_id,
            StudentAssignment.assignment_id == assignment_id,
            StudentAssignment.school_id == school_id,
        ).options(
            selectinload(StudentAssignment.attempts).selectinload(HomeworkAttempt.question),
            selectinload(StudentAssignment.hint_reveals),
        ).with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise _not_found("Submission not found")
    sa, student = row
    if sa.status not in {StudentAssignmentStatus.submitted, StudentAssignmentStatus.graded, StudentAssignmentStatus.approved}:
        raise _conflict("Only submitted homework can be graded")
    attempt_by_question = {attempt.question_id: attempt for attempt in sa.attempts}
    grades_by_question = {grade.question_id: grade for grade in req.grades}
    if set(grades_by_question) != set(attempt_by_question):
        raise _bad_request("Grades must cover every submitted answer")
    for question_id, grade in grades_by_question.items():
        attempt = attempt_by_question[question_id]
        attempt.teacher_score = grade.score
        attempt.teacher_comment = grade.comment
        attempt.correctness_score = grade.score
    sa.score = sum(grade.score for grade in req.grades) / len(req.grades)
    sa.status = StudentAssignmentStatus.approved if req.approve else StudentAssignmentStatus.graded
    sa.approved_at = datetime.now(tz=timezone.utc) if req.approve else None
    await db.commit()
    return _teacher_submission_read(sa, student)


# ── Teacher: gap digest (E2) ──────────────────────────────────────────────────

async def get_gap_digest(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> GapDigestRead:
    """Aggregate MasteryRecords for students who received this assignment.

    Same low-coverage rule as B6: below GAP_DIGEST_COVERAGE_THRESHOLD the
    digest is flagged as unreliable rather than suppressed.
    """
    a = await _load_assignment_for_teacher(db, teacher_id, school_id, assignment_id)

    # count distributed students
    sa_stmt = select(StudentAssignment).where(
        StudentAssignment.assignment_id == assignment_id,
        StudentAssignment.school_id == school_id,
    )
    sa_result = await db.execute(sa_stmt)
    student_assignments = sa_result.scalars().all()
    total = len(student_assignments)
    student_ids = [sa.student_id for sa in student_assignments]

    if not student_ids:
        return GapDigestRead(
            lesson_id=a.lesson_id,
            student_coverage=0,
            total_students=0,
            coverage_sufficient=False,
            gaps=[],
        )

    # pull MasteryRecords for these students for this lesson
    mr_stmt = select(MasteryRecord).where(
        MasteryRecord.school_id == school_id,
        MasteryRecord.lesson_id == a.lesson_id,
        MasteryRecord.student_id.in_(student_ids),
    )
    mr_result = await db.execute(mr_stmt)
    records = mr_result.scalars().all()

    # aggregate per concept
    concept_data: dict[str, list[float]] = {}
    students_with_data: set[uuid.UUID] = set()
    for r in records:
        concept_data.setdefault(r.concept_ref, []).append(r.mastery_level)
        students_with_data.add(r.student_id)

    coverage = len(students_with_data)
    coverage_ratio = coverage / total if total > 0 else 0.0

    gaps = [
        ConceptGap(
            concept_ref=concept,
            avg_mastery=round(sum(scores) / len(scores), 3),
            student_count=len(scores),
            confidence=_mastery_confidence(sum(scores) / len(scores)),
        )
        for concept, scores in concept_data.items()
    ]
    # sort weakest first
    gaps.sort(key=lambda g: g.avg_mastery)

    return GapDigestRead(
        lesson_id=a.lesson_id,
        student_coverage=coverage,
        total_students=total,
        coverage_sufficient=coverage_ratio >= GAP_DIGEST_COVERAGE_THRESHOLD,
        gaps=gaps,
    )


# ── Student: list & get ───────────────────────────────────────────────────────

async def list_student_assignments(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
) -> list[StudentAssignmentRead]:
    stmt = (
        select(StudentAssignment)
        .where(StudentAssignment.student_id == student_id, StudentAssignment.school_id == school_id)
        .options(
            selectinload(StudentAssignment.assignment).selectinload(HomeworkAssignment.questions)
        )
        .order_by(StudentAssignment.assigned_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    out = []
    for sa in rows:
        a = sa.assignment
        out.append(StudentAssignmentRead(
            id=sa.id,
            assignment_id=a.id,
            grade_level=a.grade_level,
            subject=a.subject,
            chapter=a.chapter,
            lesson_id=a.lesson_id,
            title=a.title,
            description=a.description,
            status=sa.status,
            score=sa.score,
            due_at=a.due_at,
            submitted_at=sa.submitted_at,
            question_count=len(a.questions),
        ))
    return out


async def get_student_assignment(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    student_assignment_id: uuid.UUID,
) -> StudentAssignmentWithQuestions:
    stmt = (
        select(StudentAssignment)
        .where(
            StudentAssignment.id == student_assignment_id,
            StudentAssignment.school_id == school_id,
        )
        .options(
            selectinload(StudentAssignment.assignment).selectinload(HomeworkAssignment.questions),
            selectinload(StudentAssignment.hint_reveals),
        )
    )
    result = await db.execute(stmt)
    sa = result.scalar_one_or_none()
    if sa is None:
        raise _not_found("Assignment not found")
    if sa.student_id != student_id:
        raise _forbidden()
    a = sa.assignment
    return StudentAssignmentWithQuestions(
        id=sa.id,
        assignment_id=a.id,
        grade_level=a.grade_level,
        subject=a.subject,
        chapter=a.chapter,
        lesson_id=a.lesson_id,
        title=a.title,
        description=a.description,
        status=sa.status,
        score=sa.score,
        due_at=a.due_at,
        submitted_at=sa.submitted_at,
        question_count=len(a.questions),
        questions=[_question_to_student_read(q, sum(reveal.question_id == q.id for reveal in sa.hint_reveals)) for q in a.questions],
    )


# ── Student: progressive hints, submit, and approved results ─────────────────

async def reveal_hint(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID,
    student_assignment_id: uuid.UUID, question_id: uuid.UUID,
) -> HintRevealRead:
    result = await db.execute(
        select(StudentAssignment).where(
            StudentAssignment.id == student_assignment_id, StudentAssignment.school_id == school_id,
        ).options(selectinload(StudentAssignment.assignment).selectinload(HomeworkAssignment.questions)).with_for_update()
    )
    sa = result.scalar_one_or_none()
    if sa is None:
        raise _not_found("Assignment not found")
    if sa.student_id != student_id:
        raise _forbidden()
    if sa.status in {StudentAssignmentStatus.submitted, StudentAssignmentStatus.graded, StudentAssignmentStatus.approved}:
        raise _conflict("Hints cannot be revealed after submission")
    question = next((q for q in sa.assignment.questions if q.id == question_id), None)
    if question is None:
        raise _not_found("Question not found")
    reveal_rows = await db.execute(select(HomeworkHintReveal).where(
        HomeworkHintReveal.student_assignment_id == sa.id,
        HomeworkHintReveal.question_id == question_id,
    ).with_for_update())
    next_index = len(reveal_rows.scalars().all())
    if next_index >= min(3, len(question.hints)):
        raise _conflict("No further hints are available")
    db.add(HomeworkHintReveal(
        school_id=school_id, student_assignment_id=sa.id, question_id=question_id, hint_index=next_index,
    ))
    await db.commit()
    return HintRevealRead(question_id=question_id, hint_index=next_index, hint=question.hints[next_index])


async def get_submission_result(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, student_assignment_id: uuid.UUID,
) -> SubmissionResult:
    result = await db.execute(select(StudentAssignment).where(
        StudentAssignment.id == student_assignment_id, StudentAssignment.school_id == school_id,
    ).options(selectinload(StudentAssignment.attempts).selectinload(HomeworkAttempt.question)))
    sa = result.scalar_one_or_none()
    if sa is None:
        raise _not_found("Assignment not found")
    if sa.student_id != student_id:
        raise _forbidden()
    if sa.status != StudentAssignmentStatus.approved:
        raise _conflict("Grades are available after teacher approval")
    attempts = sorted(sa.attempts, key=lambda attempt: (attempt.question.order, str(attempt.question_id)))
    return SubmissionResult(student_assignment_id=sa.id, status=sa.status, score=sa.score, results=[
        AttemptResult(question_id=attempt.question_id, answer=attempt.student_answer,
                      teacher_score=attempt.teacher_score, teacher_comment=attempt.teacher_comment)
        for attempt in attempts
    ])


async def submit_homework(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID,
    student_assignment_id: uuid.UUID, answers: list[AnswerInput],
) -> SubmissionResult:
    result = await db.execute(select(StudentAssignment).where(
        StudentAssignment.id == student_assignment_id, StudentAssignment.school_id == school_id,
    ).options(selectinload(StudentAssignment.assignment).selectinload(HomeworkAssignment.questions)).with_for_update())
    sa = result.scalar_one_or_none()
    if sa is None:
        raise _not_found()
    if sa.student_id != student_id:
        raise _forbidden()
    if sa.status in {StudentAssignmentStatus.submitted, StudentAssignmentStatus.graded, StudentAssignmentStatus.approved}:
        raise _conflict("Submitted homework cannot be edited")
    if sa.assignment.status != AssignmentStatus.distributed:
        raise _conflict("Assignment is not open for submission")
    questions = {q.id: q for q in sa.assignment.questions}
    answer_map = {answer.question_id: answer.answer for answer in answers}
    if not questions or len(answers) != len(answer_map) or set(answer_map) != set(questions):
        raise _bad_request("Answers must cover exactly the assignment's questions")
    for question_id, answer in answer_map.items():
        question = questions[question_id]
        if question.format == "mcq" and answer not in {option["id"] for option in question.options}:
            raise _bad_request("Selected answer must match one of the question's option ids")
        db.add(HomeworkAttempt(
            school_id=school_id, student_id=student_id, student_assignment_id=sa.id,
            question_id=question_id, student_answer=answer,
            is_correct=question.format == "mcq" and answer == question.correct_answer,
            correctness_score=0.0,
        ))
    sa.score = None
    sa.status = StudentAssignmentStatus.submitted
    sa.submitted_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return SubmissionResult(student_assignment_id=sa.id, status=sa.status)


async def _update_mastery_from_homework(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    assignment: HomeworkAssignment,
    questions: dict[uuid.UUID, HomeworkQuestion],
    results: list[AttemptResult],
) -> None:
    """Upsert MasteryRecord for concepts targeted by homework (E5)."""
    concept_scores: dict[str, list[float]] = {}
    for r in results:
        q = questions[r.question_id]
        if q.concept_ref:
            concept_scores.setdefault(q.concept_ref, []).append(r.correctness_score)

    for concept_ref, scores in concept_scores.items():
        avg = sum(scores) / len(scores)
        stmt = select(MasteryRecord).where(
            MasteryRecord.school_id == school_id,
            MasteryRecord.student_id == student_id,
            MasteryRecord.lesson_id == assignment.lesson_id,
            MasteryRecord.concept_ref == concept_ref,
        ).with_for_update()
        result = await db.execute(stmt)
        mr = result.scalar_one_or_none()
        if mr is None:
            mr = MasteryRecord(
                school_id=school_id,
                student_id=student_id,
                lesson_id=assignment.lesson_id,
                concept_ref=concept_ref,
                mastery_level=avg,
                confidence=_mastery_confidence(avg),
                attempt_count=len(scores),
                correct_count=sum(1 for s in scores if s >= CORRECT_THRESHOLD),
                last_attempt_at=datetime.now(tz=timezone.utc),
            )
            db.add(mr)
        else:
            # blend homework evidence with existing mastery
            total = mr.attempt_count + len(scores)
            blended = (mr.mastery_level * mr.attempt_count + avg * len(scores)) / total
            mr.mastery_level = blended
            mr.confidence = _mastery_confidence(blended)
            mr.attempt_count = total
            mr.correct_count = (mr.correct_count or 0) + sum(1 for s in scores if s >= CORRECT_THRESHOLD)
            mr.last_attempt_at = datetime.now(tz=timezone.utc)
