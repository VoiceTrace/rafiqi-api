"""The manual homework workflow's acceptance criteria, one test each.

Source of truth: teachers create homework for a grade, students answer and reveal
hints, teachers grade and approve manually. These tests make each stated criterion
executable so a regression against the product rules fails loudly.

Requires TEST_DATABASE_URL (a migrated local *_test database); the fixture is
shared with test_homework_integration and rolls everything back.
"""
import pytest

from tests.test_homework_integration import homework_api  # noqa: F401  (pytest fixture)

QUESTION = {
    "question_text": "A car pushes a trailer. What force does the trailer exert back?",
    "format": "mcq",
    "options": [{"id": "a", "text": "Equal and opposite"}, {"id": "b", "text": "Smaller"}],
    "correct_answer": "a",
    "hints": ["Forces come in pairs", "Same size", "Opposite direction"],
    "order": 0,
}


async def _published(client, tokens, *, hints=None, grade="Grade 10"):
    """Create -> add one question -> distribute. Returns (assignment_path, question_id)."""
    teacher = tokens["teacher"]
    created = await client.post("/homework/assignments", headers=teacher, json={
        "grade_level": grade, "subject": "Physics", "chapter": "Forces",
        "lesson_id": "acceptance", "title": "Acceptance quiz",
    })
    assert created.status_code == 201, created.text
    path = f"/homework/assignments/{created.json()['id']}"
    payload = {**QUESTION} if hints is None else {**QUESTION, "hints": hints}
    question = await client.post(f"{path}/questions", headers=teacher, json=payload)
    assert question.status_code == 201, question.text
    distributed = await client.post(f"{path}/distribute", headers=teacher, json={})
    assert distributed.status_code == 200, distributed.text
    return path, question.json()["id"]


async def _student_path(client, tokens, who="student"):
    listed = await client.get("/homework/me/assignments", headers=tokens[who])
    assert listed.status_code == 200, listed.text
    assert listed.json(), f"{who} sees no homework"
    return f"/homework/me/assignments/{listed.json()[0]['id']}", listed.json()[0]


@pytest.mark.asyncio
async def test_ac1_only_students_in_the_grade_receive_the_homework(homework_api):  # noqa: F811
    """Only students in the homework's grade can see and submit it."""
    client, _db, users, tokens = homework_api
    await _published(client, tokens, grade="Grade 10")

    # student and peer are Grade 10; the foreign student is in another school entirely.
    for who in ("student", "peer"):
        listed = await client.get("/homework/me/assignments", headers=tokens[who])
        assert listed.status_code == 200 and len(listed.json()) == 1, who

    outside = await client.get("/homework/me/assignments", headers=tokens["foreign"])
    assert outside.status_code == 200 and outside.json() == []


@pytest.mark.asyncio
async def test_ac1_a_grade_with_no_students_cannot_be_published(homework_api):  # noqa: F811
    client, _db, _users, tokens = homework_api
    teacher = tokens["teacher"]
    created = await client.post("/homework/assignments", headers=teacher, json={
        "grade_level": "Grade 99", "subject": "Physics", "chapter": "Forces",
        "lesson_id": "empty-grade", "title": "Nobody is in this grade",
    })
    path = f"/homework/assignments/{created.json()['id']}"
    assert (await client.post(f"{path}/questions", headers=teacher, json=QUESTION)).status_code == 201
    refused = await client.post(f"{path}/distribute", headers=teacher, json={})
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_ac2_hints_are_sequential_and_the_fourth_is_blocked(homework_api):  # noqa: F811
    """Hints are revealed one at a time; the 4th reveal is refused by the API."""
    client, _db, _users, tokens = homework_api
    _path, question_id = await _published(client, tokens)
    student_path, _ = await _student_path(client, tokens)
    reveal_url = f"{student_path}/questions/{question_id}/hints/reveal"

    for expected_index in range(3):
        revealed = await client.post(reveal_url, headers=tokens["student"])
        assert revealed.status_code == 200, revealed.text
        assert revealed.json()["hint_index"] == expected_index
        assert revealed.json()["hint"] == QUESTION["hints"][expected_index]

    fourth = await client.post(reveal_url, headers=tokens["student"])
    assert fourth.status_code == 409


@pytest.mark.asyncio
async def test_ac2_a_question_with_fewer_hints_caps_at_what_exists(homework_api):  # noqa: F811
    """Three is a maximum, not a quota — a one-hint question allows exactly one reveal."""
    client, _db, _users, tokens = homework_api
    _path, question_id = await _published(client, tokens, hints=["The only hint"])
    student_path, _ = await _student_path(client, tokens)
    reveal_url = f"{student_path}/questions/{question_id}/hints/reveal"

    quiz = await client.get(student_path, headers=tokens["student"])
    assert quiz.json()["questions"][0]["hint_count"] == 1

    assert (await client.post(reveal_url, headers=tokens["student"])).status_code == 200
    assert (await client.post(reveal_url, headers=tokens["student"])).status_code == 409


@pytest.mark.asyncio
async def test_ac2_revealed_hints_survive_a_reload(homework_api):  # noqa: F811
    """A student who spent a reveal must still see that hint after refreshing."""
    client, _db, _users, tokens = homework_api
    _path, question_id = await _published(client, tokens)
    student_path, _ = await _student_path(client, tokens)

    await client.post(f"{student_path}/questions/{question_id}/hints/reveal", headers=tokens["student"])
    await client.post(f"{student_path}/questions/{question_id}/hints/reveal", headers=tokens["student"])

    reloaded = (await client.get(student_path, headers=tokens["student"])).json()["questions"][0]
    assert reloaded["revealed_hint_count"] == 2
    assert reloaded["revealed_hints"] == QUESTION["hints"][:2]
    # The hint they have not paid for must still be withheld.
    assert QUESTION["hints"][2] not in str(reloaded)


@pytest.mark.asyncio
async def test_ac3_teacher_sees_hint_usage_per_question_when_grading(homework_api):  # noqa: F811
    """Hint usage is recorded per student per question, visible to the teacher."""
    client, _db, users, tokens = homework_api
    path, question_id = await _published(client, tokens)
    student_path, _ = await _student_path(client, tokens)

    await client.post(f"{student_path}/questions/{question_id}/hints/reveal", headers=tokens["student"])
    await client.post(f"{student_path}/submit", headers=tokens["student"],
                      json={"answers": [{"question_id": question_id, "answer": "a"}]})

    rows = {row["student_id"]: row for row in
            (await client.get(f"{path}/submissions", headers=tokens["teacher"])).json()}
    assert rows[str(users["student"].id)]["attempts"][0]["hints_revealed"] == 1


@pytest.mark.asyncio
async def test_ac4_a_submitted_homework_cannot_be_edited(homework_api):  # noqa: F811
    client, _db, _users, tokens = homework_api
    _path, question_id = await _published(client, tokens)
    student_path, _ = await _student_path(client, tokens)
    answer = {"answers": [{"question_id": question_id, "answer": "a"}]}

    assert (await client.post(f"{student_path}/submit", headers=tokens["student"], json=answer)).status_code == 200
    again = await client.post(f"{student_path}/submit", headers=tokens["student"], json=answer)
    assert again.status_code == 409

    # Hints also close once the work is handed in.
    blocked = await client.post(f"{student_path}/questions/{question_id}/hints/reveal", headers=tokens["student"])
    assert blocked.status_code == 409


@pytest.mark.asyncio
async def test_ac6_submitting_does_not_auto_grade(homework_api):  # noqa: F811
    """MCQ stores a correct option, but the submission carries no score of its own."""
    client, _db, _users, tokens = homework_api
    _path, question_id = await _published(client, tokens)
    student_path, _ = await _student_path(client, tokens)

    submitted = await client.post(f"{student_path}/submit", headers=tokens["student"],
                                  json={"answers": [{"question_id": question_id, "answer": "a"}]})
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["score"] is None
    assert submitted.json()["results"] == []


@pytest.mark.asyncio
async def test_ac7_grades_stay_hidden_until_the_teacher_approves(homework_api):  # noqa: F811
    """The regression that motivated this file: a graded-but-unapproved submission
    must look unmarked from the student's side, on every student-facing route."""
    client, _db, _users, tokens = homework_api
    path, question_id = await _published(client, tokens)
    student_path, received = await _student_path(client, tokens)
    student = tokens["student"]

    await client.post(f"{student_path}/submit", headers=student,
                      json={"answers": [{"question_id": question_id, "answer": "a"}]})

    grade_url = f"{path}/submissions/{received['id']}/grade"
    marks = {"grades": [{"question_id": question_id, "score": 1, "comment": "Good"}]}

    # Teacher enters marks but does NOT approve.
    graded = await client.post(grade_url, headers=tokens["teacher"], json={**marks, "approve": False})
    assert graded.status_code == 200 and graded.json()["status"] == "graded"

    assert (await client.get(f"{student_path}/results", headers=student)).status_code == 409
    listed = (await client.get("/homework/me/assignments", headers=student)).json()[0]
    assert listed["score"] is None, "grade leaked through the assignment list"
    detail = (await client.get(student_path, headers=student)).json()
    assert detail["score"] is None, "grade leaked through the assignment detail"

    # Teacher approves — now, and only now, the student sees it.
    approved = await client.post(grade_url, headers=tokens["teacher"], json={**marks, "approve": True})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    results = await client.get(f"{student_path}/results", headers=student)
    assert results.status_code == 200 and results.json()["score"] == 1
    assert (await client.get("/homework/me/assignments", headers=student)).json()[0]["score"] == 1


@pytest.mark.asyncio
async def test_answer_key_never_reaches_the_student(homework_api):  # noqa: F811
    client, _db, _users, tokens = homework_api
    _path, question_id = await _published(client, tokens)
    student_path, _ = await _student_path(client, tokens)

    quiz = await client.get(student_path, headers=tokens["student"])
    assert quiz.status_code == 200
    assert "correct_answer" not in quiz.text
    assert "hints" not in quiz.json()["questions"][0]
