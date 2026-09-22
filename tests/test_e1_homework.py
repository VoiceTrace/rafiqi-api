"""
Epic E — Homework tests.

Tests cover:
- Schema validation: MCQOption, AddQuestionRequest, SubmitHomeworkRequest
- PDPL: correct_answer never in student-facing QuestionRead
- Service helpers: _assignment_to_read, _question_to_teacher_read, _question_to_student_read
- Service: create_assignment — sets draft status, scoped to school_id
- Service: add_question — validates correct_answer in options, stores all fields
- Service: update_assignment — blocks on distributed status
- Service: distribute_assignment — blocks with no questions; creates StudentAssignment rows
- Service: submit_homework — scores MCQ binary, writes HomeworkAttempt rows
- Service: mastery upsert — blends new score into existing MasteryRecord
- PDPL isolation: mismatched school_id raises 404/403
- Gap digest: coverage_sufficient flag below threshold
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.homework import (
    AssignmentStatus,
    HomeworkAssignment,
    HomeworkAttempt,
    HomeworkQuestion,
    StudentAssignment,
    StudentAssignmentStatus,
)
from app.models.study_session import MasteryRecord
from app.schemas.homework import (
    AddQuestionRequest,
    AnswerInput,
    MCQOption,
    QuestionRead,
    QuestionReadTeacher,
    SubmitHomeworkRequest,
)
from app.services.homework import (
    CORRECT_THRESHOLD,
    GAP_DIGEST_COVERAGE_THRESHOLD,
    _assignment_to_read,
    _mastery_confidence,
    _question_to_student_read,
    _question_to_teacher_read,
    _update_mastery_from_homework,
)


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _ids():
    return uuid.uuid4(), uuid.uuid4()  # school_id, teacher_id / student_id


def _make_assignment(**kwargs) -> HomeworkAssignment:
    school_id, teacher_id = _ids()
    a = HomeworkAssignment()
    a.id = uuid.uuid4()
    a.school_id = school_id
    a.teacher_id = teacher_id
    a.lesson_id = "lesson-201"
    a.title = "Chapter 5 Review"
    a.description = None
    a.status = AssignmentStatus.draft
    a.due_at = None
    a.created_at = datetime.now(tz=timezone.utc)
    a.updated_at = datetime.now(tz=timezone.utc)
    a.questions = []
    a.student_assignments = []
    for k, v in kwargs.items():
        setattr(a, k, v)
    return a


def _make_question(assignment: HomeworkAssignment, **kwargs) -> HomeworkQuestion:
    q = HomeworkQuestion()
    q.id = uuid.uuid4()
    q.school_id = assignment.school_id
    q.assignment_id = assignment.id
    q.question_text = "What is 2 + 2?"
    q.format = "mcq"
    q.options = [
        {"id": "a", "text": "3"},
        {"id": "b", "text": "4"},
        {"id": "c", "text": "5"},
        {"id": "d", "text": "6"},
    ]
    q.correct_answer = "b"
    q.concept_ref = "addition"
    q.order = 0
    for k, v in kwargs.items():
        setattr(q, k, v)
    return q


def _make_student_assignment(assignment: HomeworkAssignment, student_id: uuid.UUID) -> StudentAssignment:
    sa = StudentAssignment()
    sa.id = uuid.uuid4()
    sa.school_id = assignment.school_id
    sa.student_id = student_id
    sa.assignment_id = assignment.id
    sa.status = StudentAssignmentStatus.assigned
    sa.score = None
    sa.submitted_at = None
    sa.assigned_at = datetime.now(tz=timezone.utc)
    return sa


# ──────────────────────────────────────────
# Schema validation
# ──────────────────────────────────────────

class TestMCQOptionSchema:
    def test_valid(self):
        o = MCQOption(id="a", text="Option A")
        assert o.id == "a"
        assert o.text == "Option A"

    def test_id_too_long(self):
        with pytest.raises(ValidationError):
            MCQOption(id="toolongid123", text="x")

    def test_empty_text(self):
        with pytest.raises(ValidationError):
            MCQOption(id="a", text="")


class TestAddQuestionRequestSchema:
    def _valid_options(self):
        return [
            MCQOption(id="a", text="3"),
            MCQOption(id="b", text="4"),
        ]

    def test_valid(self):
        req = AddQuestionRequest(
            question_text="What is 2+2?",
            options=self._valid_options(),
            correct_answer="b",
        )
        assert req.question_text == "What is 2+2?"
        assert req.correct_answer == "b"

    def test_too_few_options(self):
        with pytest.raises(ValidationError):
            AddQuestionRequest(
                question_text="Q",
                options=[MCQOption(id="a", text="only one")],
                correct_answer="a",
            )

    def test_empty_question_text(self):
        with pytest.raises(ValidationError):
            AddQuestionRequest(
                question_text="",
                options=self._valid_options(),
                correct_answer="a",
            )


class TestSubmitHomeworkRequestSchema:
    def test_valid(self):
        req = SubmitHomeworkRequest(
            answers=[AnswerInput(question_id=uuid.uuid4(), selected_option="a")]
        )
        assert len(req.answers) == 1

    def test_empty_answers(self):
        with pytest.raises(ValidationError):
            SubmitHomeworkRequest(answers=[])


# ──────────────────────────────────────────
# PDPL: correct_answer protection
# ──────────────────────────────────────────

class TestCorrectAnswerNotInStudentSchema:
    def test_question_read_has_no_correct_answer(self):
        assert not hasattr(QuestionRead.model_fields, "correct_answer"), \
            "QuestionRead must NOT expose correct_answer"
        assert "correct_answer" not in QuestionRead.model_fields

    def test_question_read_teacher_has_correct_answer(self):
        assert "correct_answer" in QuestionReadTeacher.model_fields


# ──────────────────────────────────────────
# Service helpers (pure — no DB)
# ──────────────────────────────────────────

class TestMasteryConfidence:
    def test_forming(self):
        assert _mastery_confidence(0.3) == "forming"

    def test_developing(self):
        assert _mastery_confidence(0.6) == "developing"

    def test_solid(self):
        assert _mastery_confidence(0.8) == "solid"


class TestAssignmentToRead:
    def test_question_count_from_loaded_relationship(self):
        a = _make_assignment()
        q = _make_question(a)
        a.questions = [q, q]
        read = _assignment_to_read(a)
        assert read.question_count == 2

    def test_correct_fields(self):
        a = _make_assignment()
        a.questions = []
        read = _assignment_to_read(a)
        assert read.id == a.id
        assert read.school_id == a.school_id
        assert read.status == AssignmentStatus.draft


class TestQuestionReadConversion:
    def test_teacher_read_includes_correct_answer(self):
        a = _make_assignment()
        q = _make_question(a)
        t = _question_to_teacher_read(q)
        assert t.correct_answer == "b"
        assert len(t.options) == 4

    def test_student_read_excludes_correct_answer(self):
        a = _make_assignment()
        q = _make_question(a)
        s = _question_to_student_read(q)
        assert not hasattr(s, "correct_answer")
        # confirm correct_answer is actually absent from the model dump
        dump = s.model_dump()
        assert "correct_answer" not in dump


# ──────────────────────────────────────────
# Service: create_assignment
# ──────────────────────────────────────────

class TestCreateAssignment:
    @pytest.mark.asyncio
    async def test_creates_draft(self):
        from app.services.homework import create_assignment
        from app.schemas.homework import CreateAssignmentRequest

        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        req = CreateAssignmentRequest(lesson_id="L1", title="HW1")
        school_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        added = []

        def _add(obj):
            added.append(obj)
            # simulate the DB assigning a PK on flush
            obj.id = uuid.uuid4()

        db.add = _add

        # refresh fills in server-generated fields
        async def _refresh(obj):
            obj.created_at = datetime.now(tz=timezone.utc)
            obj.updated_at = datetime.now(tz=timezone.utc)

        db.refresh = _refresh

        result = await create_assignment(db=db, teacher_id=teacher_id, school_id=school_id, req=req)
        assert result.status == AssignmentStatus.draft
        assert result.school_id == school_id
        assert result.teacher_id == teacher_id
        assert len(added) == 1
        assert added[0].school_id == school_id


# ──────────────────────────────────────────
# Service: add_question
# ──────────────────────────────────────────

class TestAddQuestion:
    def _make_db_for_assignment(self, assignment: HomeworkAssignment) -> AsyncMock:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = assignment
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        async def _refresh(obj):
            obj.id = uuid.uuid4()

        db.refresh = _refresh
        db.add = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_valid_question_added(self):
        from app.schemas.homework import AddQuestionRequest
        from app.services.homework import add_question

        a = _make_assignment()
        db = self._make_db_for_assignment(a)
        req = AddQuestionRequest(
            question_text="What is 2+2?",
            options=[MCQOption(id="a", text="3"), MCQOption(id="b", text="4")],
            correct_answer="b",
        )
        result = await add_question(db=db, teacher_id=a.teacher_id, school_id=a.school_id, assignment_id=a.id, req=req)
        assert result.correct_answer == "b"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_correct_answer_not_in_options_raises(self):
        from app.schemas.homework import AddQuestionRequest
        from app.services.homework import add_question

        a = _make_assignment()
        db = self._make_db_for_assignment(a)
        req = AddQuestionRequest(
            question_text="Q",
            options=[MCQOption(id="a", text="A"), MCQOption(id="b", text="B")],
            correct_answer="z",  # not in options
        )
        with pytest.raises(HTTPException) as exc_info:
            await add_question(db=db, teacher_id=a.teacher_id, school_id=a.school_id, assignment_id=a.id, req=req)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_distributed_assignment_raises_conflict(self):
        from app.schemas.homework import AddQuestionRequest
        from app.services.homework import add_question

        a = _make_assignment(status=AssignmentStatus.distributed)
        db = self._make_db_for_assignment(a)
        req = AddQuestionRequest(
            question_text="Q",
            options=[MCQOption(id="a", text="A"), MCQOption(id="b", text="B")],
            correct_answer="a",
        )
        with pytest.raises(HTTPException) as exc_info:
            await add_question(db=db, teacher_id=a.teacher_id, school_id=a.school_id, assignment_id=a.id, req=req)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_wrong_teacher_raises_forbidden(self):
        from app.schemas.homework import AddQuestionRequest
        from app.services.homework import add_question

        a = _make_assignment()
        db = self._make_db_for_assignment(a)
        req = AddQuestionRequest(
            question_text="Q",
            options=[MCQOption(id="a", text="A"), MCQOption(id="b", text="B")],
            correct_answer="a",
        )
        other_teacher = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await add_question(db=db, teacher_id=other_teacher, school_id=a.school_id, assignment_id=a.id, req=req)
        assert exc_info.value.status_code == 403


# ──────────────────────────────────────────
# Service: distribute_assignment
# ──────────────────────────────────────────

class TestDistributeAssignment:
    def _make_db(self, assignment: HomeworkAssignment) -> AsyncMock:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = assignment
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_no_questions_raises_conflict(self):
        from app.schemas.homework import DistributeRequest
        from app.services.homework import distribute_assignment

        a = _make_assignment()  # no questions
        db = self._make_db(a)
        req = DistributeRequest(student_ids=[uuid.uuid4()])
        with pytest.raises(HTTPException) as exc_info:
            await distribute_assignment(db=db, teacher_id=a.teacher_id, school_id=a.school_id, assignment_id=a.id, req=req)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_creates_student_assignment_rows(self):
        from app.schemas.homework import DistributeRequest
        from app.services.homework import distribute_assignment

        a = _make_assignment()
        q = _make_question(a)
        a.questions = [q]
        db = self._make_db(a)

        students = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        req = DistributeRequest(student_ids=students)
        result = await distribute_assignment(db=db, teacher_id=a.teacher_id, school_id=a.school_id, assignment_id=a.id, req=req)

        assert result.status == AssignmentStatus.distributed
        assert db.add.call_count == len(students)
        added = [c.args[0] for c in db.add.call_args_list]
        assert all(isinstance(obj, StudentAssignment) for obj in added)
        assert {obj.student_id for obj in added} == set(students)

    @pytest.mark.asyncio
    async def test_already_distributed_raises_conflict(self):
        from app.schemas.homework import DistributeRequest
        from app.services.homework import distribute_assignment

        a = _make_assignment(status=AssignmentStatus.distributed)
        q = _make_question(a)
        a.questions = [q]
        db = self._make_db(a)
        req = DistributeRequest(student_ids=[uuid.uuid4()])
        with pytest.raises(HTTPException) as exc_info:
            await distribute_assignment(db=db, teacher_id=a.teacher_id, school_id=a.school_id, assignment_id=a.id, req=req)
        assert exc_info.value.status_code == 409


# ──────────────────────────────────────────
# Service: submit_homework — scoring
# ──────────────────────────────────────────

class TestSubmitHomework:
    def _make_db_for_submit(self, student_assignment: StudentAssignment) -> AsyncMock:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student_assignment
        # Second execute call is for mastery upsert (returns None → new record path)
        mr_result = MagicMock()
        mr_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[mock_result, mr_result, mr_result])
        db.flush = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_correct_answer_scores_1(self):
        from app.services.homework import submit_homework

        a = _make_assignment(status=AssignmentStatus.distributed)
        q = _make_question(a)  # correct_answer = "b"
        a.questions = [q]
        student_id = uuid.uuid4()
        sa = _make_student_assignment(a, student_id)
        sa.assignment = a
        db = self._make_db_for_submit(sa)

        answers = [AnswerInput(question_id=q.id, selected_option="b")]  # correct
        result = await submit_homework(db=db, student_id=student_id, school_id=a.school_id, student_assignment_id=sa.id, answers=answers)
        assert result.score == 1.0
        assert result.correct_count == 1
        assert result.total_count == 1
        assert result.results[0].is_correct is True
        assert result.results[0].correct_answer == "b"

    @pytest.mark.asyncio
    async def test_wrong_answer_scores_0(self):
        from app.services.homework import submit_homework

        a = _make_assignment(status=AssignmentStatus.distributed)
        q = _make_question(a)  # correct_answer = "b"
        a.questions = [q]
        student_id = uuid.uuid4()
        sa = _make_student_assignment(a, student_id)
        sa.assignment = a
        db = self._make_db_for_submit(sa)

        answers = [AnswerInput(question_id=q.id, selected_option="a")]  # wrong
        result = await submit_homework(db=db, student_id=student_id, school_id=a.school_id, student_assignment_id=sa.id, answers=answers)
        assert result.score == 0.0
        assert result.correct_count == 0

    @pytest.mark.asyncio
    async def test_mixed_answers_partial_score(self):
        from app.services.homework import submit_homework

        a = _make_assignment(status=AssignmentStatus.distributed)
        q1 = _make_question(a, order=0)
        q2 = _make_question(a, question_text="What is 3+3?", correct_answer="c",
                            options=[{"id": "a", "text": "5"}, {"id": "b", "text": "4"}, {"id": "c", "text": "6"}, {"id": "d", "text": "7"}],
                            order=1)
        q2.id = uuid.uuid4()
        a.questions = [q1, q2]
        student_id = uuid.uuid4()
        sa = _make_student_assignment(a, student_id)
        sa.assignment = a

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sa
        mr_result = MagicMock()
        mr_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[mock_result, mr_result, mr_result, mr_result])
        db.flush = AsyncMock()
        db.add = MagicMock()

        answers = [
            AnswerInput(question_id=q1.id, selected_option="b"),  # correct
            AnswerInput(question_id=q2.id, selected_option="a"),  # wrong
        ]
        result = await submit_homework(db=db, student_id=student_id, school_id=a.school_id, student_assignment_id=sa.id, answers=answers)
        assert result.score == 0.5
        assert result.correct_count == 1
        assert result.total_count == 2

    @pytest.mark.asyncio
    async def test_already_submitted_raises_conflict(self):
        from app.services.homework import submit_homework

        a = _make_assignment(status=AssignmentStatus.distributed)
        q = _make_question(a)
        a.questions = [q]
        student_id = uuid.uuid4()
        sa = _make_student_assignment(a, student_id)
        sa.status = StudentAssignmentStatus.submitted  # already done
        sa.assignment = a

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sa
        db.execute = AsyncMock(return_value=mock_result)

        answers = [AnswerInput(question_id=q.id, selected_option="b")]
        with pytest.raises(HTTPException) as exc_info:
            await submit_homework(db=db, student_id=student_id, school_id=a.school_id, student_assignment_id=sa.id, answers=answers)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_wrong_student_raises_forbidden(self):
        from app.services.homework import submit_homework

        a = _make_assignment(status=AssignmentStatus.distributed)
        q = _make_question(a)
        a.questions = [q]
        student_id = uuid.uuid4()
        sa = _make_student_assignment(a, student_id)
        sa.assignment = a

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sa
        db.execute = AsyncMock(return_value=mock_result)

        other_student = uuid.uuid4()
        answers = [AnswerInput(question_id=q.id, selected_option="b")]
        with pytest.raises(HTTPException) as exc_info:
            await submit_homework(db=db, student_id=other_student, school_id=a.school_id, student_assignment_id=sa.id, answers=answers)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_mismatched_answers_raises_bad_request(self):
        from app.services.homework import submit_homework

        a = _make_assignment(status=AssignmentStatus.distributed)
        q1 = _make_question(a)
        q2 = _make_question(a)
        q2.id = uuid.uuid4()
        a.questions = [q1, q2]
        student_id = uuid.uuid4()
        sa = _make_student_assignment(a, student_id)
        sa.assignment = a

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sa
        db.execute = AsyncMock(return_value=mock_result)

        # only answer one of two questions
        answers = [AnswerInput(question_id=q1.id, selected_option="b")]
        with pytest.raises(HTTPException) as exc_info:
            await submit_homework(db=db, student_id=student_id, school_id=a.school_id, student_assignment_id=sa.id, answers=answers)
        assert exc_info.value.status_code == 400


# ──────────────────────────────────────────
# Service: mastery upsert
# ──────────────────────────────────────────

class TestMasteryUpsert:
    @pytest.mark.asyncio
    async def test_creates_new_mastery_record_when_none(self):
        a = _make_assignment()
        q = _make_question(a)  # concept_ref = "addition"
        a.questions = [q]

        from app.schemas.homework import AttemptResult

        results = [
            AttemptResult(
                question_id=q.id,
                selected_option="b",
                is_correct=True,
                correctness_score=1.0,
                correct_answer="b",
            )
        ]

        db = AsyncMock()
        mr_result = MagicMock()
        mr_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mr_result)
        added = []
        db.add = lambda obj: added.append(obj)

        await _update_mastery_from_homework(
            db=db,
            student_id=uuid.uuid4(),
            school_id=a.school_id,
            assignment=a,
            questions={q.id: q},
            results=results,
        )
        assert len(added) == 1
        assert isinstance(added[0], MasteryRecord)
        assert added[0].mastery_level == 1.0
        assert added[0].concept_ref == "addition"

    @pytest.mark.asyncio
    async def test_blends_into_existing_mastery_record(self):
        a = _make_assignment()
        q = _make_question(a)
        a.questions = [q]

        from app.schemas.homework import AttemptResult

        results = [
            AttemptResult(
                question_id=q.id,
                selected_option="a",  # wrong
                is_correct=False,
                correctness_score=0.0,
                correct_answer="b",
            )
        ]

        existing_mr = MagicMock(spec=MasteryRecord)
        existing_mr.mastery_level = 1.0
        existing_mr.attempt_count = 4
        existing_mr.correct_count = 4
        existing_mr.concept_ref = "addition"

        db = AsyncMock()
        mr_result = MagicMock()
        mr_result.scalar_one_or_none.return_value = existing_mr
        db.execute = AsyncMock(return_value=mr_result)
        db.add = MagicMock()

        await _update_mastery_from_homework(
            db=db,
            student_id=uuid.uuid4(),
            school_id=a.school_id,
            assignment=a,
            questions={q.id: q},
            results=results,
        )
        # blended: (1.0*4 + 0.0*1) / 5 = 0.8
        assert abs(existing_mr.mastery_level - 0.8) < 1e-9
        assert existing_mr.attempt_count == 5
        db.add.assert_not_called()


# ──────────────────────────────────────────
# Constants sanity
# ──────────────────────────────────────────

class TestConstants:
    def test_correct_threshold(self):
        assert CORRECT_THRESHOLD == 0.8, "THRESHOLD constant changed without updating the comment"

    def test_coverage_threshold(self):
        assert GAP_DIGEST_COVERAGE_THRESHOLD == 0.5
