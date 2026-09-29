"""Students must not see a grade before the teacher approves, and must not lose
hints they already revealed. Both are acceptance criteria of the manual workflow.
"""
import uuid

import pytest

from app.models.homework import StudentAssignmentStatus
from app.services import homework as svc
from tests.test_homework_validation import _make_assignment, _make_question, _make_student_assignment


@pytest.mark.parametrize("status", [
    StudentAssignmentStatus.assigned,
    StudentAssignmentStatus.in_progress,
    StudentAssignmentStatus.submitted,
    StudentAssignmentStatus.graded,
])
def test_score_is_hidden_until_the_teacher_approves(status):
    """`graded` is the dangerous one: the teacher has entered marks but not released them."""
    assignment = _make_assignment()
    received = _make_student_assignment(assignment, uuid.uuid4(), status=status, score=0.73)
    assert svc._student_visible_score(received) is None


def test_score_is_released_once_approved():
    assignment = _make_assignment()
    received = _make_student_assignment(
        assignment, uuid.uuid4(), status=StudentAssignmentStatus.approved, score=0.73,
    )
    assert svc._student_visible_score(received) == 0.73


def test_revealed_hints_come_back_so_a_reload_does_not_lose_them():
    assignment = _make_assignment()
    question = _make_question(assignment, hints=["Think in pairs", "Same size", "Opposite direction"])
    read = svc._question_to_student_read(question, revealed_hint_count=2)
    assert read.revealed_hints == ["Think in pairs", "Same size"]
    assert read.revealed_hint_count == 2
    assert read.hint_count == 3


def test_unrevealed_hints_are_never_sent():
    assignment = _make_assignment()
    question = _make_question(assignment, hints=["First", "Second", "Third"])
    read = svc._question_to_student_read(question, revealed_hint_count=0)
    assert read.revealed_hints == []
    assert read.hint_count == 3


def test_hint_count_reflects_a_question_authored_with_fewer_hints():
    """A one-hint question must not advertise three, or the client offers a
    reveal the API answers with 409."""
    assignment = _make_assignment()
    question = _make_question(assignment, hints=["The only hint"])
    read = svc._question_to_student_read(question, revealed_hint_count=1)
    assert read.hint_count == 1
    assert read.revealed_hints == ["The only hint"]


def test_hint_count_never_exceeds_the_cap():
    assignment = _make_assignment()
    question = _make_question(assignment, hints=["a", "b", "c", "d"])
    read = svc._question_to_student_read(question, revealed_hint_count=4)
    assert read.hint_count == svc.MAX_HINTS_PER_QUESTION
    assert len(read.revealed_hints) == svc.MAX_HINTS_PER_QUESTION
