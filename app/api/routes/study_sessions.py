import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_student
from app.models.study_session import Question, StudySession
from app.schemas.study_session import (
    AdvanceStageRequest,
    AttemptRead,
    AttemptResult,
    CreateSessionRequest,
    ExplainRequest,
    ExplanationRead,
    MasteryRecordRead,
    PlanSessionRequest,
    QuestionRead,
    SessionRead,
    SessionWithQuestions,
    SubmitAttemptRequest,
)
from app.services import study_session as svc

router = APIRouter(prefix="/study-sessions", tags=["study-sessions"])


@router.post("", response_model=SessionRead, status_code=201, summary="Start a new study session")
async def create_session(
    body: CreateSessionRequest,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SessionRead:
    session = await svc.create_session(
        lesson_id=body.lesson_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        db=db,
    )
    return SessionRead.model_validate(session)


# NOTE: /me/mastery must be declared before /{session_id} to avoid "me" being
# interpreted as a UUID session_id
@router.get(
    "/me/mastery",
    response_model=list[MasteryRecordRead],
    summary="Get my mastery records (optionally filtered by lesson_id)",
)
async def get_my_mastery(
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
    lesson_id: str | None = Query(default=None),
) -> list[MasteryRecordRead]:
    records = await svc.list_mastery_records(
        school_id=current_user.school_id,
        student_id=current_user.id,
        db=db,
        lesson_id=lesson_id,
    )
    return [MasteryRecordRead.model_validate(r) for r in records]


@router.get(
    "/{session_id}",
    response_model=SessionWithQuestions,
    summary="Get session with all its questions",
)
async def get_session(
    session_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SessionWithQuestions:
    session = await svc.get_session(
        session_id=session_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        db=db,
    )
    return SessionWithQuestions.model_validate(session)


@router.post(
    "/{session_id}/plan",
    response_model=SessionRead,
    summary="Plan session — Rafiqi sets concept order, transitions setup→review",
)
async def plan_session(
    session_id: uuid.UUID,
    body: PlanSessionRequest,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SessionRead:
    session = await svc.plan_session(
        session_id=session_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        lesson_content=body.lesson_content,
        student_profile_override=body.student_profile,
        db=db,
    )
    return SessionRead.model_validate(session)


@router.post(
    "/{session_id}/advance",
    response_model=SessionRead,
    summary="Advance to the next stage (review→check_in→deepen→wrap_up)",
)
async def advance_stage(
    session_id: uuid.UUID,
    body: AdvanceStageRequest,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SessionRead:
    session = await svc.advance_stage(
        session_id=session_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        to_stage=body.to_stage,
        db=db,
    )
    return SessionRead.model_validate(session)


@router.post(
    "/{session_id}/questions",
    response_model=QuestionRead,
    status_code=201,
    summary="Generate next question for the current concept (check_in or deepen only)",
)
async def get_next_question(
    session_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> QuestionRead:
    question = await svc.get_next_question(
        session_id=session_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        db=db,
    )
    return QuestionRead.model_validate(question)


@router.post(
    "/{session_id}/questions/{question_id}/attempts",
    response_model=AttemptResult,
    status_code=201,
    summary="Submit an answer — returns feedback + hint if score < 0.8 and retries remain",
)
async def submit_attempt(
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    body: SubmitAttemptRequest,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> AttemptResult:
    attempt, feedback, hint_text, confirmed = await svc.submit_attempt(
        question_id=question_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        student_response=body.student_response,
        db=db,
    )

    stage_result = await db.execute(
        select(StudySession.current_stage)
        .join(Question, Question.session_id == StudySession.id)
        .where(
            StudySession.id == session_id,
            StudySession.school_id == current_user.school_id,
        )
    )
    session_stage = stage_result.scalar_one_or_none() or "unknown"

    return AttemptResult(
        attempt=AttemptRead.model_validate(attempt),
        feedback=feedback,
        hint_text=hint_text,
        hint_level=attempt.hint_level,
        concept_confirmed=confirmed,
        max_attempts_reached=attempt.attempt_number >= 3,
        session_stage=session_stage,
    )


@router.post(
    "/{session_id}/concepts/next",
    response_model=SessionRead,
    summary="Move to the next concept within the current stage",
)
async def advance_concept(
    session_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SessionRead:
    session = await svc.advance_concept(
        session_id=session_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        db=db,
    )
    return SessionRead.model_validate(session)


@router.post(
    "/{session_id}/explain",
    response_model=ExplanationRead,
    summary="Ask Rafiqi to explain a concept (available in any active stage)",
)
async def explain_concept(
    session_id: uuid.UUID,
    body: ExplainRequest,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> ExplanationRead:
    explanation_text = await svc.explain_concept(
        session_id=session_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        concept_ref=body.concept_ref,
        student_question=body.student_question,
        lesson_context=body.lesson_context,
        db=db,
    )
    return ExplanationRead(concept_ref=body.concept_ref, explanation_text=explanation_text)


@router.post(
    "/{session_id}/close",
    response_model=SessionRead,
    summary="Close session — computes MasteryRecords for all concepts, generates summary card",
)
async def close_session(
    session_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SessionRead:
    session = await svc.close_session(
        session_id=session_id,
        school_id=current_user.school_id,
        student_id=current_user.id,
        db=db,
    )
    return SessionRead.model_validate(session)
