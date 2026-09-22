"""Epic E — Homework routes.

Teacher endpoints  : /homework/assignments  (CRUD + distribute + gap-digest)
Student endpoints  : /homework/me/assignments  (list + get + submit)
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session, require_student, require_teacher
from app.schemas.homework import (
    AddQuestionRequest,
    AssignmentRead,
    AssignmentWithQuestions,
    CreateAssignmentRequest,
    DistributeRequest,
    GapDigestRead,
    QuestionReadTeacher,
    StudentAssignmentRead,
    StudentAssignmentWithQuestions,
    SubmissionResult,
    SubmitHomeworkRequest,
    UpdateAssignmentRequest,
    UpdateQuestionRequest,
)
from app.services import homework as svc

router = APIRouter(prefix="/homework", tags=["homework"])


# ── Teacher: assignment CRUD ──────────────────────────────────────────────────

@router.post(
    "/assignments",
    response_model=AssignmentRead,
    status_code=201,
    summary="Create a new homework assignment (draft)",
)
async def create_assignment(
    body: CreateAssignmentRequest,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentRead:
    return await svc.create_assignment(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        req=body,
    )


@router.get(
    "/assignments",
    response_model=list[AssignmentRead],
    summary="List my assignments (optionally filtered by lesson_id)",
)
async def list_assignments(
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
    lesson_id: str | None = Query(default=None),
) -> list[AssignmentRead]:
    return await svc.list_assignments(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        lesson_id=lesson_id,
    )


@router.get(
    "/assignments/{assignment_id}",
    response_model=AssignmentWithQuestions,
    summary="Get assignment with all questions (teacher view, includes correct answers)",
)
async def get_assignment(
    assignment_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentWithQuestions:
    return await svc.get_assignment_teacher(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
    )


@router.patch(
    "/assignments/{assignment_id}",
    response_model=AssignmentRead,
    summary="Update assignment title / description / due_at (draft only)",
)
async def update_assignment(
    assignment_id: uuid.UUID,
    body: UpdateAssignmentRequest,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentRead:
    return await svc.update_assignment(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
        req=body,
    )


@router.delete(
    "/assignments/{assignment_id}",
    status_code=204,
    summary="Delete an assignment (draft only)",
)
async def delete_assignment(
    assignment_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await svc.delete_assignment(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
    )


# ── Teacher: question CRUD ────────────────────────────────────────────────────

@router.post(
    "/assignments/{assignment_id}/questions",
    response_model=QuestionReadTeacher,
    status_code=201,
    summary="Add an MCQ question to a draft assignment",
)
async def add_question(
    assignment_id: uuid.UUID,
    body: AddQuestionRequest,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> QuestionReadTeacher:
    return await svc.add_question(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
        req=body,
    )


@router.patch(
    "/assignments/{assignment_id}/questions/{question_id}",
    response_model=QuestionReadTeacher,
    summary="Update a question (draft assignment only)",
)
async def update_question(
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
    body: UpdateQuestionRequest,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> QuestionReadTeacher:
    return await svc.update_question(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
        question_id=question_id,
        req=body,
    )


@router.delete(
    "/assignments/{assignment_id}/questions/{question_id}",
    status_code=204,
    summary="Delete a question (draft assignment only)",
)
async def delete_question(
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await svc.delete_question(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
        question_id=question_id,
    )


# ── Teacher: distribute ───────────────────────────────────────────────────────

@router.post(
    "/assignments/{assignment_id}/distribute",
    response_model=AssignmentRead,
    summary="Bulk-distribute assignment to student list (transitions draft → distributed)",
)
async def distribute_assignment(
    assignment_id: uuid.UUID,
    body: DistributeRequest,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> AssignmentRead:
    return await svc.distribute_assignment(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
        req=body,
    )


# ── Teacher: gap digest ───────────────────────────────────────────────────────

@router.get(
    "/assignments/{assignment_id}/gap-digest",
    response_model=GapDigestRead,
    summary="Class-level mastery gap digest for this assignment's lesson (E2)",
)
async def get_gap_digest(
    assignment_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_teacher)],
    db: AsyncSession = Depends(get_db_session),
) -> GapDigestRead:
    return await svc.get_gap_digest(
        db=db,
        teacher_id=current_user.id,
        school_id=current_user.school_id,
        assignment_id=assignment_id,
    )


# ── Student: list & get ───────────────────────────────────────────────────────

@router.get(
    "/me/assignments",
    response_model=list[StudentAssignmentRead],
    summary="List my assigned homework",
)
async def list_my_assignments(
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> list[StudentAssignmentRead]:
    return await svc.list_student_assignments(
        db=db,
        student_id=current_user.id,
        school_id=current_user.school_id,
    )


@router.get(
    "/me/assignments/{student_assignment_id}",
    response_model=StudentAssignmentWithQuestions,
    summary="Get assignment with questions — no correct answers revealed until after submit",
)
async def get_my_assignment(
    student_assignment_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> StudentAssignmentWithQuestions:
    return await svc.get_student_assignment(
        db=db,
        student_id=current_user.id,
        school_id=current_user.school_id,
        student_assignment_id=student_assignment_id,
    )


# ── Student: submit ───────────────────────────────────────────────────────────

@router.post(
    "/me/assignments/{student_assignment_id}/submit",
    response_model=SubmissionResult,
    summary="Submit homework — reveals correct answers in response (E5)",
)
async def submit_homework(
    student_assignment_id: uuid.UUID,
    body: SubmitHomeworkRequest,
    current_user: Annotated[CurrentUser, Depends(require_student)],
    db: AsyncSession = Depends(get_db_session),
) -> SubmissionResult:
    return await svc.submit_homework(
        db=db,
        student_id=current_user.id,
        school_id=current_user.school_id,
        student_assignment_id=student_assignment_id,
        answers=body.answers,
    )
