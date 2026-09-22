"""
Study session service — Epic D business logic.

All public functions take (db, school_id, student_id, ...) and enforce
PDPL tenant isolation — every query is scoped to school_id.
The Rafiqi interface is injected (default: MockRafiqi) so tests can swap it.
"""

import uuid
from collections import Counter
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ErrorCode
from app.models.study_session import (
    Attempt,
    MasteryConfidence,
    MasteryRecord,
    Question,
    SessionStage,
    SessionStatus,
    StudySession,
)
from app.services.rafiqi_interface import RafiqiInterface
from app.services.rafiqi_mock import MockRafiqi

# Valid stage transitions (from → to)
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    SessionStage.SETUP: {SessionStage.REVIEW},
    SessionStage.REVIEW: {SessionStage.CHECK_IN},
    SessionStage.CHECK_IN: {SessionStage.DEEPEN, SessionStage.WRAP_UP},
    SessionStage.DEEPEN: {SessionStage.WRAP_UP},
    SessionStage.WRAP_UP: set(),
}

# Hint ladder mastery weights (D4)
_HINT_WEIGHTS = {0: 1.0, 1: 0.7, 2: 0.4, 3: 0.1}

CORRECT_THRESHOLD = 0.8   # score >= 0.8 → concept confirmed
MAX_ATTEMPTS = 3          # per question


def _default_rafiqi() -> RafiqiInterface:
    return MockRafiqi()


# ──────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────

def _not_found(msg: str = "Not found") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": ErrorCode.NOT_FOUND, "message": msg}},
    )


def _forbidden(msg: str = "Access denied") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": {"code": ErrorCode.FORBIDDEN, "message": msg}},
    )


def _conflict(msg: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": {"code": ErrorCode.CONFLICT, "message": msg}},
    )


async def _get_session_scoped(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    db: AsyncSession,
    *,
    load_questions: bool = False,
) -> StudySession:
    stmt = select(StudySession).where(
        StudySession.id == session_id,
        StudySession.school_id == school_id,  # PDPL hard-scope
    )
    if load_questions:
        stmt = stmt.options(selectinload(StudySession.questions))
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise _not_found("Session not found")
    return session


async def _get_question_scoped(
    question_id: uuid.UUID,
    school_id: uuid.UUID,
    db: AsyncSession,
) -> Question:
    result = await db.execute(
        select(Question).where(
            Question.id == question_id,
            Question.school_id == school_id,  # PDPL hard-scope
        )
    )
    question = result.scalar_one_or_none()
    if question is None:
        raise _not_found("Question not found")
    return question


def _compute_mastery(attempts: list[Attempt]) -> tuple[float, int, int, str | None]:
    """
    Returns (mastery_level, attempt_count, correct_count, dominant_error_type).
    D4 formula: Σ(weight(hint_level) × correctness_score) / attempt_count
    """
    if not attempts:
        return 0.0, 0, 0, None

    weighted_sum = sum(
        _HINT_WEIGHTS.get(a.hint_level, 0.1) * a.correctness_score for a in attempts
    )
    mastery_level = weighted_sum / len(attempts)
    correct_count = sum(1 for a in attempts if a.correctness_score >= CORRECT_THRESHOLD)

    error_types = [a.error_type for a in attempts if a.error_type]
    dominant = Counter(error_types).most_common(1)[0][0] if error_types else None

    return mastery_level, len(attempts), correct_count, dominant


def _mastery_confidence(mastery_level: float) -> str:
    if mastery_level >= 0.75:
        return MasteryConfidence.SOLID
    if mastery_level >= 0.4:
        return MasteryConfidence.DEVELOPING
    return MasteryConfidence.FORMING


# ──────────────────────────────────────────
# Public API
# ──────────────────────────────────────────

async def create_session(
    lesson_id: str,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    db: AsyncSession,
) -> StudySession:
    session = StudySession(
        school_id=school_id,
        student_id=student_id,
        lesson_id=lesson_id,
        status=SessionStatus.OPEN,
        current_stage=SessionStage.SETUP,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    db: AsyncSession,
) -> StudySession:
    session = await _get_session_scoped(session_id, school_id, db, load_questions=True)
    if session.student_id != student_id:
        raise _forbidden()
    return session


async def plan_session(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    lesson_content: dict,
    student_profile_override: dict | None,
    db: AsyncSession,
    rafiqi: RafiqiInterface | None = None,
) -> StudySession:
    if rafiqi is None:
        rafiqi = _default_rafiqi()

    session = await _get_session_scoped(session_id, school_id, db)
    if session.student_id != student_id:
        raise _forbidden()
    if session.current_stage != SessionStage.SETUP:
        raise _conflict("Session already planned")

    student_profile = student_profile_override or {}
    plan = await rafiqi.plan_session(lesson_content, student_profile)

    session.concepts_order = plan.concepts_order
    session.current_stage = SessionStage.REVIEW
    session.status = SessionStatus.IN_PROGRESS

    await db.commit()
    await db.refresh(session)
    return session


async def advance_stage(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    to_stage: str,
    db: AsyncSession,
) -> StudySession:
    session = await _get_session_scoped(session_id, school_id, db)
    if session.student_id != student_id:
        raise _forbidden()
    if session.status == SessionStatus.CLOSED:
        raise _conflict("Session is already closed")

    allowed = _ALLOWED_TRANSITIONS.get(session.current_stage, set())
    if to_stage not in allowed:
        raise _conflict(
            f"Cannot transition from '{session.current_stage}' to '{to_stage}'"
        )

    session.current_stage = to_stage
    await db.commit()
    await db.refresh(session)
    return session


async def get_next_question(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    db: AsyncSession,
    rafiqi: RafiqiInterface | None = None,
) -> Question:
    if rafiqi is None:
        rafiqi = _default_rafiqi()

    session = await _get_session_scoped(session_id, school_id, db)
    if session.student_id != student_id:
        raise _forbidden()
    if session.current_stage not in (SessionStage.CHECK_IN, SessionStage.DEEPEN):
        raise _conflict(
            f"Questions are only generated during check_in or deepen stage, not '{session.current_stage}'"
        )
    if not session.concepts_order:
        raise _conflict("Session has no concept plan — call /plan first")

    idx = session.current_concept_index
    if idx >= len(session.concepts_order):
        raise _conflict("All concepts have been covered")

    concept_ref = session.concepts_order[idx]

    # Gather prior errors on this concept within this session
    prior_attempts_result = await db.execute(
        select(Attempt)
        .join(Question, Attempt.question_id == Question.id)
        .where(
            Question.session_id == session_id,
            Question.concept_ref == concept_ref,
            Attempt.school_id == school_id,
        )
    )
    prior_attempts = prior_attempts_result.scalars().all()
    prior_errors = [a.error_type for a in prior_attempts if a.error_type]

    generated = await rafiqi.generate_question(
        concept_ref=concept_ref,
        stage=session.current_stage,
        lesson_context={"lesson_id": session.lesson_id},
        prior_errors=prior_errors,
    )

    question = Question(
        school_id=school_id,
        session_id=session_id,
        student_id=student_id,
        concept_ref=concept_ref,
        stage=session.current_stage,
        question_text=generated.question_text,
        internal_answer_key=generated.internal_answer_key,
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return question


async def submit_attempt(
    question_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    student_response: str,
    db: AsyncSession,
    rafiqi: RafiqiInterface | None = None,
) -> tuple[Attempt, str, str | None, bool]:
    """
    Returns (attempt, feedback_text, hint_text, concept_confirmed).
    hint_text is None when score >= CORRECT_THRESHOLD or max attempts reached.
    """
    if rafiqi is None:
        rafiqi = _default_rafiqi()

    question = await _get_question_scoped(question_id, school_id, db)
    if question.student_id != student_id:
        raise _forbidden()

    # Count prior attempts on this question
    prior_result = await db.execute(
        select(Attempt).where(
            Attempt.question_id == question_id,
            Attempt.school_id == school_id,
        )
    )
    prior_attempts = prior_result.scalars().all()
    attempt_number = len(prior_attempts) + 1

    if attempt_number > MAX_ATTEMPTS:
        raise _conflict("Maximum attempts reached for this question")

    current_hint_level = max((a.hint_level for a in prior_attempts), default=0)

    scored = await rafiqi.score_response(
        question_text=question.question_text,
        internal_answer_key=question.internal_answer_key,
        student_response=student_response,
        hint_level=current_hint_level,
    )

    attempt = Attempt(
        school_id=school_id,
        question_id=question_id,
        student_id=student_id,
        student_response=student_response,
        correctness_score=scored.correctness_score,
        error_type=scored.error_type,
        hint_level=current_hint_level,
        attempt_number=attempt_number,
    )
    db.add(attempt)
    await db.flush()  # get attempt.id before generating hint

    hint_text: str | None = None
    next_hint_level = current_hint_level + 1

    if (
        scored.correctness_score < CORRECT_THRESHOLD
        and attempt_number < MAX_ATTEMPTS
        and next_hint_level <= 3
    ):
        hint = await rafiqi.generate_hint(
            question_text=question.question_text,
            internal_answer_key=question.internal_answer_key,
            student_response=student_response,
            hint_level=next_hint_level,
        )
        hint_text = hint.hint_text

    await db.commit()
    await db.refresh(attempt)
    return attempt, scored.feedback_text, hint_text, scored.concept_confirmed


async def advance_concept(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    db: AsyncSession,
) -> StudySession:
    """Move to the next concept in concepts_order."""
    session = await _get_session_scoped(session_id, school_id, db)
    if session.student_id != student_id:
        raise _forbidden()
    if not session.concepts_order:
        raise _conflict("No concept plan")

    if session.current_concept_index + 1 >= len(session.concepts_order):
        raise _conflict("No more concepts — advance stage to wrap_up")

    session.current_concept_index += 1
    await db.commit()
    await db.refresh(session)
    return session


async def explain_concept(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    concept_ref: str,
    student_question: str | None,
    lesson_context: dict | None,
    db: AsyncSession,
    rafiqi: RafiqiInterface | None = None,
) -> str:
    if rafiqi is None:
        rafiqi = _default_rafiqi()

    session = await _get_session_scoped(session_id, school_id, db)
    if session.student_id != student_id:
        raise _forbidden()

    explanation = await rafiqi.explain_concept(
        concept_ref=concept_ref,
        lesson_context=lesson_context or {"lesson_id": session.lesson_id},
        student_question=student_question,
    )
    return explanation.explanation_text


async def close_session(
    session_id: uuid.UUID,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    db: AsyncSession,
    rafiqi: RafiqiInterface | None = None,
) -> StudySession:
    """
    D6: aggregate mastery, upsert MasteryRecords, generate summary, close session.
    All queries scoped to school_id.
    """
    if rafiqi is None:
        rafiqi = _default_rafiqi()

    session = await _get_session_scoped(session_id, school_id, db)
    if session.student_id != student_id:
        raise _forbidden()
    if session.status == SessionStatus.CLOSED:
        raise _conflict("Session is already closed")

    # Load all attempts for this session through Question join
    attempts_result = await db.execute(
        select(Attempt, Question.concept_ref)
        .join(Question, Attempt.question_id == Question.id)
        .where(
            Question.session_id == session_id,
            Attempt.school_id == school_id,  # PDPL scope
        )
    )
    rows = attempts_result.all()

    # Group attempts by concept_ref
    by_concept: dict[str, list[Attempt]] = {}
    for attempt, concept_ref in rows:
        by_concept.setdefault(concept_ref, []).append(attempt)

    mastery_by_concept: dict[str, float] = {}
    error_summary: dict[str, str | None] = {}

    for concept_ref, attempts in by_concept.items():
        mastery_level, attempt_count, correct_count, dominant_error = _compute_mastery(attempts)
        confidence = _mastery_confidence(mastery_level)
        last_at = max(a.created_at for a in attempts)

        mastery_by_concept[concept_ref] = mastery_level
        error_summary[concept_ref] = dominant_error

        # Upsert MasteryRecord — scoped to school_id + student_id (PDPL)
        existing_result = await db.execute(
            select(MasteryRecord).where(
                MasteryRecord.school_id == school_id,
                MasteryRecord.student_id == student_id,
                MasteryRecord.lesson_id == session.lesson_id,
                MasteryRecord.concept_ref == concept_ref,
            )
        )
        record = existing_result.scalar_one_or_none()

        if record is None:
            record = MasteryRecord(
                school_id=school_id,
                student_id=student_id,
                lesson_id=session.lesson_id,
                concept_ref=concept_ref,
            )
            db.add(record)

        record.attempt_count = attempt_count
        record.correct_count = correct_count
        record.mastery_level = mastery_level
        record.dominant_error_type = dominant_error
        record.confidence = confidence
        record.last_attempt_at = last_at

    # Generate summary card
    summary = await rafiqi.generate_summary(
        session_concepts=list(by_concept.keys()) or (session.concepts_order or []),
        mastery_by_concept=mastery_by_concept,
        error_summary=error_summary,
    )

    session.summary_card = {
        "summary_text": summary.summary_text,
        "strong_concepts": summary.strong_concepts,
        "gap_concepts": summary.gap_concepts,
        "encouragement": summary.encouragement,
    }
    session.status = SessionStatus.CLOSED
    session.closed_at = datetime.now(timezone.utc)
    session.current_stage = SessionStage.WRAP_UP

    await db.commit()
    await db.refresh(session)
    return session


async def list_mastery_records(
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    db: AsyncSession,
    lesson_id: str | None = None,
) -> list[MasteryRecord]:
    stmt = select(MasteryRecord).where(
        MasteryRecord.school_id == school_id,   # PDPL scope
        MasteryRecord.student_id == student_id,
    )
    if lesson_id:
        stmt = stmt.where(MasteryRecord.lesson_id == lesson_id)
    stmt = stmt.order_by(MasteryRecord.updated_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
