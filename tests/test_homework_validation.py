"""Regression coverage for authoring and submission input integrity."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.homework import (
    AddQuestionRequest, AnswerInput, CreateAssignmentRequest, DistributeRequest,
    SubmitHomeworkRequest, UpdateAssignmentRequest, UpdateQuestionRequest,
)
from app.services import homework as svc
from tests.test_e1_homework import _make_assignment, _make_question, _make_student_assignment


@pytest.mark.parametrize("schema,payload", [
    (CreateAssignmentRequest, {"lesson_id": "lesson", "title": "   "}),
    (CreateAssignmentRequest, {"lesson_id": "x" * 101, "title": "Title"}),
    (CreateAssignmentRequest, {"lesson_id": "lesson", "title": "Title", "due_at": "2026-10-01T09:00"}),
    (UpdateAssignmentRequest, {"title": ""}),
    (UpdateAssignmentRequest, {"title": "x" * 501}),
    (UpdateQuestionRequest, {"question_text": "   "}),
    (UpdateQuestionRequest, {"options": []}),
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


def test_duplicate_students_and_answers_rejected():
    identifier = uuid.uuid4()
    with pytest.raises(ValidationError):
        DistributeRequest(student_ids=[identifier, identifier])
    with pytest.raises(ValidationError):
        SubmitHomeworkRequest(answers=[
            {"question_id": identifier, "selected_option": "a"},
            {"question_id": identifier, "selected_option": "b"},
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
async def test_distribution_rejects_unmatched_recipient_before_writes():
    assignment = _make_assignment()
    assignment.questions = [_make_question(assignment)]
    valid, invalid = uuid.uuid4(), uuid.uuid4()
    db = make_db(assignment, [valid])
    with pytest.raises(HTTPException) as error:
        await svc.distribute_assignment(db, assignment.teacher_id, assignment.school_id,
                                        assignment.id, DistributeRequest(student_ids=[valid, invalid]))
    assert error.value.status_code == 400
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    assert assignment.status == "draft"


@pytest.mark.asyncio
async def test_distribution_rejects_question_without_three_hints():
    assignment = _make_assignment()
    question = _make_question(assignment, hints=[])
    assignment.questions = [question]
    db = make_db(assignment)
    with pytest.raises(HTTPException) as error:
        await svc.distribute_assignment(db, assignment.teacher_id, assignment.school_id,
                                        assignment.id, DistributeRequest(student_ids=[uuid.uuid4()]))
    assert error.value.status_code == 409
    db.add.assert_not_called()


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
@pytest.mark.parametrize("invalid", ["unknown_option", "duplicate_question", "closed_assignment"])
async def test_invalid_submission_cannot_write_attempts_or_mastery(invalid):
    assignment = _make_assignment(status="closed" if invalid == "closed_assignment" else "distributed")
    question = _make_question(assignment)
    assignment.questions = [question]
    student = uuid.uuid4()
    received = _make_student_assignment(assignment, student)
    received.assignment = assignment
    db = make_db(received)
    answers = [AnswerInput(question_id=question.id, selected_option="z" if invalid == "unknown_option" else "a")]
    if invalid == "duplicate_question":
        answers.append(AnswerInput(question_id=question.id, selected_option="b"))
    with pytest.raises(HTTPException) as error:
        await svc.submit_homework(db, student, assignment.school_id, received.id, answers)
    assert error.value.status_code == (409 if invalid == "closed_assignment" else 400)
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
