"""
Epic D — Study Session tests.

Tests cover:
- Schema validation (CreateSessionRequest, SubmitAttemptRequest)
- MockRafiqi satisfies RafiqiInterface Protocol
- Service: create_session
- Service: plan_session — sets concepts_order, transitions stage to review
- Service: advance_stage — valid and invalid transitions (incl. PDPL scope)
- Service: get_next_question — uses current concept, stores school_id
- Service: submit_attempt — scoring, hint population, max attempt guard
- Service: close_session — mastery computation, MasteryRecord upsert
- PDPL isolation: school_id mismatch raises 403/404 in service layer
- Mastery formula: hint-weighted scoring
"""
import uuid
from collections import Counter
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.study_session import (
    Attempt,
    MasteryConfidence,
    MasteryRecord,
    Question,
    SessionStage,
    SessionStatus,
    StudySession,
)
from app.schemas.study_session import (
    CreateSessionRequest,
    SubmitAttemptRequest,
)
from app.services.rafiqi_interface import RafiqiInterface
from app.services.rafiqi_mock import MockRafiqi
from app.services.study_session import (
    CORRECT_THRESHOLD,
    MAX_ATTEMPTS,
    _compute_mastery,
    _mastery_confidence,
    advance_stage,
    close_session,
    create_session,
    get_next_question,
    plan_session,
    submit_attempt,
)


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _ids():
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4()  # school, student, session


def _make_session(**kwargs) -> StudySession:
    school_id, student_id, session_id = _ids()
    s = StudySession()
    s.id = session_id
    s.school_id = school_id
    s.student_id = student_id
    s.lesson_id = "lesson-101"
    s.status = SessionStatus.OPEN
    s.current_stage = SessionStage.SETUP
    s.current_concept_index = 0
    s.concepts_order = None
    s.summary_card = None
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _make_question(session: StudySession, **kwargs) -> Question:
    q = Question()
    q.id = uuid.uuid4()
    q.school_id = session.school_id
    q.session_id = session.id
    q.student_id = session.student_id
    q.concept_ref = "concept_1"
    q.stage = SessionStage.CHECK_IN
    q.question_text = "What is X?"
    q.internal_answer_key = "X is the key concept."
    for k, v in kwargs.items():
        setattr(q, k, v)
    return q


def _make_attempt(question: Question, **kwargs) -> Attempt:
    a = Attempt()
    a.id = uuid.uuid4()
    a.school_id = question.school_id
    a.question_id = question.id
    a.student_id = question.student_id
    a.student_response = "My answer"
    a.correctness_score = 0.5
    a.error_type = "recall_error"
    a.hint_level = 0
    a.attempt_number = 1
    a.created_at = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    for k, v in kwargs.items():
        setattr(a, k, v)
    return a


def _mock_db_returning(obj):
    """Returns an AsyncMock DB that yields `obj` from execute().scalar_one_or_none()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = obj
    mock_result.scalars.return_value.all.return_value = []
    mock_result.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = mock_result
    return db


# ──────────────────────────────────────────
# Schema validation
# ──────────────────────────────────────────

def test_create_session_rejects_empty_lesson_id():
    with pytest.raises(ValidationError):
        CreateSessionRequest(lesson_id="")


def test_create_session_accepts_valid_lesson_id():
    req = CreateSessionRequest(lesson_id="lesson-42")
    assert req.lesson_id == "lesson-42"


def test_submit_attempt_rejects_empty_response():
    with pytest.raises(ValidationError):
        SubmitAttemptRequest(student_response="")


def test_submit_attempt_accepts_valid_response():
    req = SubmitAttemptRequest(student_response="My thoughtful answer here.")
    assert req.student_response.startswith("My")


# ──────────────────────────────────────────
# MockRafiqi satisfies Protocol
# ──────────────────────────────────────────

def test_mock_rafiqi_satisfies_protocol():
    assert isinstance(MockRafiqi(), RafiqiInterface)


@pytest.mark.asyncio
async def test_mock_rafiqi_plan_session_uses_lesson_concepts():
    rafiqi = MockRafiqi()
    plan = await rafiqi.plan_session(
        lesson_content={"concepts": ["c1", "c2"]},
        student_profile={},
    )
    assert plan.concepts_order == ["c1", "c2"]
    assert plan.recommended_stage == "review"


@pytest.mark.asyncio
async def test_mock_rafiqi_score_short_response_low_score():
    rafiqi = MockRafiqi()
    scored = await rafiqi.score_response("Q?", "key", "short", hint_level=0)
    assert scored.correctness_score < CORRECT_THRESHOLD
    assert scored.error_type is not None


@pytest.mark.asyncio
async def test_mock_rafiqi_score_long_response_high_score():
    rafiqi = MockRafiqi()
    long_response = "x" * 100
    scored = await rafiqi.score_response("Q?", "key", long_response, hint_level=0)
    assert scored.correctness_score >= CORRECT_THRESHOLD
    assert scored.error_type is None
    assert scored.concept_confirmed is True


@pytest.mark.asyncio
async def test_mock_rafiqi_hint_level_3_reveals_answer():
    rafiqi = MockRafiqi()
    hint = await rafiqi.generate_hint("Q?", "key", "attempt", hint_level=3)
    assert hint.reveals_answer is True


# ──────────────────────────────────────────
# Mastery formula (D4) — pure unit tests
# ──────────────────────────────────────────

def test_compute_mastery_empty_returns_zeros():
    level, count, correct, dominant = _compute_mastery([])
    assert level == 0.0
    assert count == 0
    assert correct == 0
    assert dominant is None


def test_compute_mastery_all_correct_no_hints():
    """hint=0 → weight=1.0; score=1.0 → mastery=1.0"""
    attempts = [_make_attempt(_make_question(_make_session()), correctness_score=1.0, hint_level=0) for _ in range(3)]
    level, count, correct, dominant = _compute_mastery(attempts)
    assert abs(level - 1.0) < 1e-9
    assert count == 3
    assert correct == 3


def test_compute_mastery_hint_3_weight_penalty():
    """hint=3 → weight=0.1; score=1.0 → mastery=0.1 (answer was revealed)"""
    attempt = _make_attempt(_make_question(_make_session()), correctness_score=1.0, hint_level=3)
    level, _, _, _ = _compute_mastery([attempt])
    assert abs(level - 0.1) < 1e-9


def test_compute_mastery_mixed_hints():
    """1 attempt hint=0 score=1.0, 1 attempt hint=2 score=0.5 → (1.0 + 0.4*0.5)/2 = 0.6"""
    s = _make_session()
    q = _make_question(s)
    a1 = _make_attempt(q, correctness_score=1.0, hint_level=0)
    a2 = _make_attempt(q, correctness_score=0.5, hint_level=2)
    level, count, _, _ = _compute_mastery([a1, a2])
    expected = (1.0 * 1.0 + 0.4 * 0.5) / 2
    assert abs(level - expected) < 1e-9
    assert count == 2


def test_mastery_confidence_thresholds():
    assert _mastery_confidence(0.0) == MasteryConfidence.FORMING
    assert _mastery_confidence(0.39) == MasteryConfidence.FORMING
    assert _mastery_confidence(0.40) == MasteryConfidence.DEVELOPING
    assert _mastery_confidence(0.74) == MasteryConfidence.DEVELOPING
    assert _mastery_confidence(0.75) == MasteryConfidence.SOLID
    assert _mastery_confidence(1.0) == MasteryConfidence.SOLID


def test_compute_mastery_dominant_error():
    s = _make_session()
    q = _make_question(s)
    attempts = [
        _make_attempt(q, error_type="recall_error"),
        _make_attempt(q, error_type="recall_error"),
        _make_attempt(q, error_type="conceptual_gap"),
    ]
    _, _, _, dominant = _compute_mastery(attempts)
    assert dominant == "recall_error"


# ──────────────────────────────────────────
# Service: create_session
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_session_sets_defaults():
    school_id, student_id, _ = _ids()
    db = AsyncMock()

    created_session = None

    async def _fake_refresh(obj):
        nonlocal created_session
        created_session = obj

    db.refresh.side_effect = _fake_refresh

    await create_session("lesson-1", school_id, student_id, db)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    args = db.add.call_args[0]
    session = args[0]
    assert isinstance(session, StudySession)
    assert session.school_id == school_id
    assert session.student_id == student_id
    assert session.lesson_id == "lesson-1"
    assert session.status == SessionStatus.OPEN
    assert session.current_stage == SessionStage.SETUP


# ──────────────────────────────────────────
# Service: plan_session
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_session_sets_concepts_and_advances_stage():
    session = _make_session()
    db = _mock_db_returning(session)
    rafiqi = MockRafiqi()

    await plan_session(
        session_id=session.id,
        school_id=session.school_id,
        student_id=session.student_id,
        lesson_content={"concepts": ["alpha", "beta"]},
        student_profile_override=None,
        db=db,
        rafiqi=rafiqi,
    )

    assert session.concepts_order == ["alpha", "beta"]
    assert session.current_stage == SessionStage.REVIEW
    assert session.status == SessionStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_plan_session_rejects_already_planned():
    session = _make_session(current_stage=SessionStage.REVIEW)
    db = _mock_db_returning(session)

    with pytest.raises(HTTPException) as exc:
        await plan_session(
            session_id=session.id,
            school_id=session.school_id,
            student_id=session.student_id,
            lesson_content={},
            student_profile_override=None,
            db=db,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_plan_session_pdpl_wrong_school_not_found():
    session = _make_session()
    db = _mock_db_returning(None)  # PDPL scope query returns nothing

    with pytest.raises(HTTPException) as exc:
        await plan_session(
            session_id=session.id,
            school_id=uuid.uuid4(),  # different school
            student_id=session.student_id,
            lesson_content={},
            student_profile_override=None,
            db=db,
        )

    assert exc.value.status_code == 404


# ──────────────────────────────────────────
# Service: advance_stage
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_advance_stage_valid_transition():
    session = _make_session(current_stage=SessionStage.REVIEW, status=SessionStatus.IN_PROGRESS)
    db = _mock_db_returning(session)

    await advance_stage(
        session_id=session.id,
        school_id=session.school_id,
        student_id=session.student_id,
        to_stage=SessionStage.CHECK_IN,
        db=db,
    )

    assert session.current_stage == SessionStage.CHECK_IN


@pytest.mark.asyncio
async def test_advance_stage_invalid_transition_raises_409():
    session = _make_session(current_stage=SessionStage.REVIEW, status=SessionStatus.IN_PROGRESS)
    db = _mock_db_returning(session)

    with pytest.raises(HTTPException) as exc:
        await advance_stage(
            session_id=session.id,
            school_id=session.school_id,
            student_id=session.student_id,
            to_stage=SessionStage.DEEPEN,  # can't skip check_in
            db=db,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_advance_stage_wrong_student_raises_403():
    session = _make_session(current_stage=SessionStage.REVIEW, status=SessionStatus.IN_PROGRESS)
    db = _mock_db_returning(session)

    with pytest.raises(HTTPException) as exc:
        await advance_stage(
            session_id=session.id,
            school_id=session.school_id,
            student_id=uuid.uuid4(),  # wrong student
            to_stage=SessionStage.CHECK_IN,
            db=db,
        )

    assert exc.value.status_code == 403


# ──────────────────────────────────────────
# Service: get_next_question
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_next_question_creates_question_with_school_id():
    session = _make_session(
        current_stage=SessionStage.CHECK_IN,
        status=SessionStatus.IN_PROGRESS,
        concepts_order=["photosynthesis", "osmosis"],
        current_concept_index=0,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = session
    mock_result.scalars.return_value.all.return_value = []  # no prior attempts

    db = AsyncMock()
    db.execute.return_value = mock_result
    db.add = MagicMock()  # db.add is sync in SQLAlchemy

    await get_next_question(
        session_id=session.id,
        school_id=session.school_id,
        student_id=session.student_id,
        db=db,
        rafiqi=MockRafiqi(),
    )

    db.add.assert_called_once()
    created_question = db.add.call_args[0][0]
    assert isinstance(created_question, Question)
    assert created_question.school_id == session.school_id  # PDPL
    assert created_question.concept_ref == "photosynthesis"
    assert created_question.stage == SessionStage.CHECK_IN
    assert created_question.internal_answer_key  # not empty


@pytest.mark.asyncio
async def test_get_next_question_wrong_stage_raises_409():
    session = _make_session(
        current_stage=SessionStage.REVIEW,
        concepts_order=["c1"],
    )
    db = _mock_db_returning(session)

    with pytest.raises(HTTPException) as exc:
        await get_next_question(
            session_id=session.id,
            school_id=session.school_id,
            student_id=session.student_id,
            db=db,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_get_next_question_no_plan_raises_409():
    session = _make_session(
        current_stage=SessionStage.CHECK_IN,
        concepts_order=None,  # not planned yet
    )
    db = _mock_db_returning(session)

    with pytest.raises(HTTPException) as exc:
        await get_next_question(
            session_id=session.id,
            school_id=session.school_id,
            student_id=session.student_id,
            db=db,
        )

    assert exc.value.status_code == 409


# ──────────────────────────────────────────
# Service: submit_attempt
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_attempt_first_correct_no_hint():
    session = _make_session()
    question = _make_question(session)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = question
    mock_result.scalars.return_value.all.return_value = []  # no prior attempts

    db = AsyncMock()
    db.execute.return_value = mock_result
    db.flush = AsyncMock()

    long_response = "x" * 100
    attempt, feedback, hint_text, confirmed = await submit_attempt(
        question_id=question.id,
        school_id=question.school_id,
        student_id=question.student_id,
        student_response=long_response,
        db=db,
        rafiqi=MockRafiqi(),
    )

    assert attempt.correctness_score >= CORRECT_THRESHOLD
    assert attempt.error_type is None
    assert hint_text is None  # correct → no hint
    assert confirmed is True
    assert attempt.attempt_number == 1
    assert attempt.school_id == question.school_id  # PDPL


@pytest.mark.asyncio
async def test_submit_attempt_wrong_answer_returns_hint():
    session = _make_session()
    question = _make_question(session)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = question
    mock_result.scalars.return_value.all.return_value = []  # first attempt

    db = AsyncMock()
    db.execute.return_value = mock_result
    db.flush = AsyncMock()

    attempt, feedback, hint_text, confirmed = await submit_attempt(
        question_id=question.id,
        school_id=question.school_id,
        student_id=question.student_id,
        student_response="idk",  # short → low score
        db=db,
        rafiqi=MockRafiqi(),
    )

    assert attempt.correctness_score < CORRECT_THRESHOLD
    assert hint_text is not None  # hint provided
    assert confirmed is False


@pytest.mark.asyncio
async def test_submit_attempt_max_attempts_raises_409():
    session = _make_session()
    question = _make_question(session)

    # Simulate 3 prior attempts already stored
    prior_attempts = [
        _make_attempt(question, attempt_number=i + 1) for i in range(MAX_ATTEMPTS)
    ]

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = question
    mock_result.scalars.return_value.all.return_value = prior_attempts

    db = AsyncMock()
    db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await submit_attempt(
            question_id=question.id,
            school_id=question.school_id,
            student_id=question.student_id,
            student_response="another try",
            db=db,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_submit_attempt_pdpl_wrong_student_raises_403():
    session = _make_session()
    question = _make_question(session)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = question
    mock_result.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await submit_attempt(
            question_id=question.id,
            school_id=question.school_id,
            student_id=uuid.uuid4(),  # wrong student
            student_response="answer",
            db=db,
        )

    assert exc.value.status_code == 403


# ──────────────────────────────────────────
# Service: close_session — mastery aggregation
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_session_computes_mastery_and_closes():
    session = _make_session(
        current_stage=SessionStage.WRAP_UP,
        status=SessionStatus.IN_PROGRESS,
        concepts_order=["c1"],
    )
    question = _make_question(session, concept_ref="c1")

    # Two attempts: hint=0 score=1.0 and hint=1 score=0.0
    # mastery = (1.0*1.0 + 0.7*0.0) / 2 = 0.5 → "developing"
    a1 = _make_attempt(question, correctness_score=1.0, hint_level=0, error_type=None)
    a2 = _make_attempt(question, correctness_score=0.0, hint_level=1, error_type="recall_error")

    call_count = [0]

    async def _side_effect(stmt):
        call_count[0] += 1
        mock_result = MagicMock()
        if call_count[0] == 1:
            # First call: _get_session_scoped
            mock_result.scalar_one_or_none.return_value = session
        elif call_count[0] == 2:
            # Second call: attempts join query
            mock_result.all.return_value = [(a1, "c1"), (a2, "c1")]
        else:
            # MasteryRecord lookup — doesn't exist yet
            mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    db = AsyncMock()
    db.execute.side_effect = _side_effect

    await close_session(
        session_id=session.id,
        school_id=session.school_id,
        student_id=session.student_id,
        db=db,
        rafiqi=MockRafiqi(),
    )

    assert session.status == SessionStatus.CLOSED
    assert session.closed_at is not None
    assert session.summary_card is not None
    assert "summary_text" in session.summary_card


@pytest.mark.asyncio
async def test_close_session_already_closed_raises_409():
    session = _make_session(status=SessionStatus.CLOSED)
    db = _mock_db_returning(session)

    with pytest.raises(HTTPException) as exc:
        await close_session(
            session_id=session.id,
            school_id=session.school_id,
            student_id=session.student_id,
            db=db,
        )

    assert exc.value.status_code == 409


# ──────────────────────────────────────────
# PDPL — school_id isolation enforced
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_session_pdpl_different_school_not_found():
    """
    PDPL hard rule: school_id is always part of the WHERE clause.
    When the caller's school_id doesn't match the session's, the query
    returns nothing (simulate with None) → 404 raised.
    """
    db = _mock_db_returning(None)  # PDPL-scoped query returns nothing

    with pytest.raises(HTTPException) as exc:
        from app.services.study_session import get_session
        await get_session(
            session_id=uuid.uuid4(),
            school_id=uuid.uuid4(),   # different school
            student_id=uuid.uuid4(),
            db=db,
        )

    assert exc.value.status_code == 404
