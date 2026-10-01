"""Contract tests for the manual, grade-scoped homework workflow."""
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.homework import (
    AddQuestionRequest, AnswerInput, GradeSubmissionRequest, MCQOption,
    QuestionRead, SubmitHomeworkRequest,
)


def test_mcq_requires_correct_option() -> None:
    with pytest.raises(ValidationError):
        AddQuestionRequest(question_text="Q", format="mcq", options=[MCQOption(id="a", text="A"), MCQOption(id="b", text="B")], correct_answer="c")


def test_short_note_has_no_options_or_answer_key() -> None:
    question = AddQuestionRequest(question_text="Explain your reasoning", format="short_note", hints=["Use one example"])
    assert question.options == []
    assert question.correct_answer is None


@pytest.mark.parametrize("hints", [["one", "two", "three", "four"], ["one", " "]])
def test_hints_are_limited_to_three_and_nonempty(hints: list[str]) -> None:
    with pytest.raises(ValidationError):
        AddQuestionRequest(question_text="Q", format="short_note", hints=hints)


def test_student_question_contract_never_exposes_answer_or_unrevealed_hints() -> None:
    fields = QuestionRead.model_fields
    assert "correct_answer" not in fields
    # The full authored hint list must never reach the student; only the hints
    # they have already spent a reveal on come back, via `revealed_hints`.
    assert "hints" not in fields
    assert {"hint_count", "revealed_hint_count", "revealed_hints"}.issubset(fields)


def test_submission_accepts_mcq_and_short_note_answers() -> None:
    request = SubmitHomeworkRequest(answers=[
        AnswerInput(question_id=uuid.uuid4(), answer="b"),
        AnswerInput(question_id=uuid.uuid4(), answer="A short written explanation."),
    ])
    assert len(request.answers) == 2


def test_grade_submission_needs_each_question_once() -> None:
    question_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        GradeSubmissionRequest(grades=[
            {"question_id": question_id, "score": 1},
            {"question_id": question_id, "score": 0},
        ])
