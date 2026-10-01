"""Regression coverage for authoring and submission input integrity."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.homework import (
    AssignmentStatus, HomeworkAssignment, HomeworkQuestion, StudentAssignment,
    StudentAssignmentStatus,
)
from app.schemas.homework import (
    AddQuestionRequest, AnswerInput, CreateAssignmentRequest, DistributeRequest,
    SubmitHomeworkRequest, UpdateAssignmentRequest, UpdateQuestionRequest,
)
from app.services import homework as svc

ASSIGNMENT_FIELDS = {
    "grade_level": "grade-10", "subject": "Physics",
    "chapter": "Forces and Motion", "lesson_id": "lesson-newton3",
}


def _make_assignment(**overrides) -> HomeworkAssignment:
    # created_at/updated_at are server defaults, so an unsaved instance needs them
    # set explicitly or AssignmentRead validation fails on None.
    now = datetime.now(tz=timezone.utc)
    values = {
        "id": uuid.uuid4(), "school_id": uuid.uuid4(), "teacher_id": uuid.uuid4(),
        "title": "Newton's Third Law", "description": None,
        "status": AssignmentStatus.draft, "due_at": None,
        "created_at": now, "updated_at": now, **ASSIGNMENT_FIELDS,
    }
    values.update(overrides)
    assignment = HomeworkAssignment(**values)
    assignment.questions = []
    return assignment


def _make_question(assignment: HomeworkAssignment, **overrides) -> HomeworkQuestion:
    values = {
        "id": uuid.uuid4(), "school_id": assignment.school_id, "assignment_id": assignment.id,
        "question_text": "Which force acts back on the car?", "format": "mcq",
        "options": [{"id": "a", "text": "Equal and opposite"}, {"id": "b", "text": "Smaller"}],
        "correct_answer": "a", "hints": ["Think in pairs", "Same size", "Opposite direction"],
        "concept_ref": "newton3", "order": 0,
    }
    values.update(overrides)
    return HomeworkQuestion(**values)


def _make_student_assignment(assignment: HomeworkAssignment, student_id: uuid.UUID, **overrides) -> StudentAssignment:
    values = {
        "id": uuid.uuid4(), "school_id": assignment.school_id, "student_id": student_id,
        "assignment_id": assignment.id, "status": StudentAssignmentStatus.assigned,
        "score": None, "submitted_at": None, "approved_at": None,
    }
    values.update(overrides)
    received = StudentAssignment(**values)
    received.hint_reveals = []
    received.attempts = []
    return received


@pytest.mark.parametrize("schema,payload", [
    (CreateAssignmentRequest, {**ASSIGNMENT_FIELDS, "title": "   "}),
    (CreateAssignmentRequest, {**ASSIGNMENT_FIELDS, "lesson_id": "x" * 101, "title": "Title"}),
    (CreateAssignmentRequest, {**ASSIGNMENT_FIELDS, "title": "Title", "due_at": "2026-10-01T09:00"}),
    (UpdateAssignmentRequest, {"title": ""}),
    (UpdateAssignmentRequest, {"title": "x" * 501}),
    (UpdateQuestionRequest, {"question_text": "   "}),
    (UpdateQuestionRequest, {"correct_answer": "x" * 11}),
    (UpdateQuestionRequest, {"concept_ref": "x" * 201}),
    (UpdateQuestionRequest, {"order": -1}),
])
def test_invalid_authoring_fields(schema, payload):
    with pytest.raises(ValidationError):
        schema(**payload)


@pytest.mark.parametrize("schema", [AddQuestionRequest, UpdateQuestionRequest])
def test_duplicate_option_ids_rejected(schema):
    with pytest.raises(ValidationError):
        schema(question_text="Q", correct_answer="a", options=[
            {"id": "a", "text": "One"}, {"id": "a", "text": "Two"},
        ])


def test_same_question_cannot_be_answered_twice():
    identifier = uuid.uuid4()
    with pytest.raises(ValidationError):
        SubmitHomeworkRequest(answers=[
            {"question_id": identifier, "answer": "a"},
            {"question_id": identifier, "answer": "b"},
        ])


def make_db(*rows):
    db = AsyncMock()
    db.add = MagicMock()
    results = []
    for row in rows:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        result.scalars.return_value.all.return_value = row if isinstance(row, list) else []
        results.append(result)
    db.execute.side_effect = results
    return db


@pytest.mark.asyncio
async def test_options_only_patch_cannot_remove_correct_answer():
    assignment = _make_assignment()
    question = _make_question(assignment)
    db = make_db(assignment, question)
    with pytest.raises(HTTPException) as error:
        await svc.update_question(db, assignment.teacher_id, assignment.school_id,
                                  assignment.id, question.id, UpdateQuestionRequest(options=[
                                      {"id": "c", "text": "C"}, {"id": "d", "text": "D"},
                                  ]))
    assert error.value.status_code == 400
    assert question.options[0]["id"] == "a"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_null_clears_optional_assignment_fields():
    assignment = _make_assignment(description="Old description")
    db = make_db(assignment)
    result = await svc.update_assignment(db, assignment.teacher_id, assignment.school_id,
                                        assignment.id, UpdateAssignmentRequest(description=None, due_at=None))
    assert result.description is None
    assert result.due_at is None


@pytest.mark.asyncio
async def test_distribution_rejects_question_with_too_many_hints():
    assignment = _make_assignment()
    assignment.questions = [_make_question(assignment, hints=["1", "2", "3", "4"])]
    db = make_db(assignment)
    with pytest.raises(HTTPException) as error:
        await svc.distribute_assignment(db, assignment.teacher_id, assignment.school_id,
                                        assignment.id, DistributeRequest())
    assert error.value.status_code == 409
    db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("hints", [[], ["only one"], ["one", "two"]])
async def test_distribution_allows_fewer_than_the_maximum_hints(hints):
    """Hints are capped at three, not required to be three."""
    assignment = _make_assignment()
    assignment.questions = [_make_question(assignment, hints=hints)]
    student_id = uuid.uuid4()
    db = make_db(assignment, [student_id])
    await svc.distribute_assignment(db, assignment.teacher_id, assignment.school_id,
                                    assignment.id, DistributeRequest())
    assert assignment.status == AssignmentStatus.distributed
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_distribution_without_students_in_grade_is_rejected():
    assignment = _make_assignment()
    assignment.questions = [_make_question(assignment)]
    db = make_db(assignment, [])
    with pytest.raises(HTTPException) as error:
        await svc.distribute_assignment(db, assignment.teacher_id, assignment.school_id,
                                        assignment.id, DistributeRequest())
    assert error.value.status_code == 409
    db.add.assert_not_called()
    assert assignment.status == AssignmentStatus.draft


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["distributed", "closed"])
async def test_non_draft_metadata_cannot_change(status):
    assignment = _make_assignment(status=status)
    db = make_db(assignment)
    with pytest.raises(HTTPException) as error:
        await svc.update_assignment(db, assignment.teacher_id, assignment.school_id,
                                    assignment.id, UpdateAssignmentRequest(title="Changed"))
    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["unknown_option", "missing_question", "closed_assignment"])
async def test_invalid_submission_cannot_write_attempts(invalid):
    assignment = _make_assignment(status="closed" if invalid == "closed_assignment" else "distributed")
    question = _make_question(assignment)
    assignment.questions = [question, _make_question(assignment, order=1)]
    student = uuid.uuid4()
    received = _make_student_assignment(assignment, student)
    received.assignment = assignment
    db = make_db(received)
    answers = [AnswerInput(question_id=question.id, answer="z" if invalid == "unknown_option" else "a")]
    if invalid != "missing_question":
        answers.append(AnswerInput(question_id=assignment.questions[1].id, answer="a"))
    with pytest.raises(HTTPException) as error:
        await svc.submit_homework(db, student, assignment.school_id, received.id, answers)
    assert error.value.status_code == (409 if invalid == "closed_assignment" else 400)
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_submitted_homework_cannot_be_resubmitted():
    assignment = _make_assignment(status="distributed")
    assignment.questions = [_make_question(assignment)]
    student = uuid.uuid4()
    received = _make_student_assignment(assignment, student, status=StudentAssignmentStatus.submitted)
    received.assignment = assignment
    db = make_db(received)
    with pytest.raises(HTTPException) as error:
        await svc.submit_homework(db, student, assignment.school_id, received.id,
                                  [AnswerInput(question_id=assignment.questions[0].id, answer="a")])
    assert error.value.status_code == 409
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
