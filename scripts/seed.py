"""Development seed — one school, a multi-grade roster, and homework for everybody.

Run with: python scripts/seed.py
  --catalog-only   seed only the global review catalog and stop

Homework is published to a whole grade, so every seeded student carries a
grade_level and every grade gets its own copy of each assignment. That is the
point of this script: log in as any seeded student and there is work waiting.

Reruns are safe. The school, the users and the assignments are each looked up
before being created, and the submitted/graded states are only simulated for
assignments this run actually created — replaying them would hit the same
conflicts a second submission does in the product.

Writes go through app.services.homework rather than the ORM directly, so the
seeded rows are the ones the real endpoints would have produced.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.homework import HomeworkAssignment, HomeworkQuestion
from app.models.school import School
from app.models.user import User, UserRole
from app.schemas.homework import (
    AddQuestionRequest,
    AnswerInput,
    CreateAssignmentRequest,
    DistributeRequest,
    GradeAnswerInput,
    GradeSubmissionRequest,
    MCQOption,
)
from app.services import homework as hw
from app.services.review_catalog import catalog_seed, seed_catalog

engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

SCHOOL_NAME = "Al-Noor Academy"
TEACHER_PASSWORD = "teacher123"
STUDENT_PASSWORD = "student123"

TEACHERS = [
    ("teacher@alnoor.edu.sa", "Ahmed Al-Rashid"),
    ("teacher2@alnoor.edu.sa", "Fatima Al-Saleh"),
]

# The first two Grade 10 accounts keep the addresses earlier seeds used, so
# existing bookmarks and test notes still log in.
STUDENTS: dict[str, list[tuple[str, str]]] = {
    "Grade 9": [
        ("student3@alnoor.edu.sa", "Layla Al-Qahtani"),
        ("student4@alnoor.edu.sa", "Yousef Al-Ghamdi"),
        ("student5@alnoor.edu.sa", "Noura Al-Shehri"),
        ("student6@alnoor.edu.sa", "Khalid Al-Dosari"),
    ],
    "Grade 10": [
        ("student@alnoor.edu.sa", "Sara Al-Otaibi"),
        ("student2@alnoor.edu.sa", "Omar Al-Harbi"),
        ("student7@alnoor.edu.sa", "Maha Al-Zahrani"),
        ("student8@alnoor.edu.sa", "Faisal Al-Mutairi"),
    ],
    "Grade 11": [
        ("student9@alnoor.edu.sa", "Reem Al-Subaie"),
        ("student10@alnoor.edu.sa", "Turki Al-Anazi"),
        ("student11@alnoor.edu.sa", "Hessa Al-Juhani"),
        ("student12@alnoor.edu.sa", "Bandar Al-Balawi"),
    ],
}

SHORT_NOTE_ANSWER = (
    "The two surfaces in contact decide the size of the force, and it always acts "
    "against the direction the object is sliding."
)

# One assignment per chapter is left untouched for everyone; these two are the
# ones the script advances, so the teacher views have real submissions to show.
SUBMITTED_CHAPTER = "energy"
GRADED_CHAPTER = "fractions"


async def ensure_school(db: AsyncSession) -> School:
    school = await db.scalar(select(School).where(School.name == SCHOOL_NAME))
    if school is None:
        school = School(id=uuid.uuid4(), name=SCHOOL_NAME)
        db.add(school)
        await db.commit()
        await db.refresh(school)
    return school


async def ensure_user(
    db: AsyncSession, school: School, email: str, full_name: str,
    role: UserRole, grade_level: str | None, password: str,
) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            id=uuid.uuid4(), school_id=school.id, email=email, full_name=full_name,
            role=role, grade_level=grade_level, hashed_password=hash_password(password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


def question_requests(catalog: dict, chapter_id: str) -> list[AddQuestionRequest]:
    """Turn a chapter's curated review questions into teacher-authored homework.

    Reusing the catalog keeps the homework text real and its concept_ref aligned
    with the lesson, which is what the teacher gap digest groups answers by.
    """
    requests = []
    for lesson in [row for row in catalog["lessons"] if row["chapter_id"] == chapter_id]:
        for question in lesson["content"]["en"]["questions"]:
            order = len(requests)
            if question["kind"] == "choice":
                requests.append(AddQuestionRequest(
                    question_text=question["text"],
                    format="mcq",
                    options=[MCQOption(id=o["id"], text=o["text"]) for o in question["options"]],
                    correct_answer=question["answer"],
                    hints=question["hints"],
                    concept_ref=question["concept_ref"],
                    order=order,
                ))
            else:
                requests.append(AddQuestionRequest(
                    question_text=question["text"],
                    format="short_note",
                    hints=question["hints"],
                    concept_ref=question["concept_ref"],
                    order=order,
                ))
    return requests


async def ensure_assignment(
    db: AsyncSession, teacher: User, school: School, grade_level: str,
    subject: str, chapter: str, lesson_id: str, title: str, description: str,
    due_in_days: int, questions: list[AddQuestionRequest],
) -> tuple[uuid.UUID, list[uuid.UUID], bool]:
    """Create, fill and distribute one assignment. Returns (id, question ids, created)."""
    existing = await db.scalar(
        select(HomeworkAssignment).where(
            HomeworkAssignment.school_id == school.id,
            HomeworkAssignment.grade_level == grade_level,
            HomeworkAssignment.title == title,
        )
    )
    if existing is not None:
        rows = await db.execute(
            select(HomeworkQuestion.id)
            .where(HomeworkQuestion.assignment_id == existing.id)
            .order_by(HomeworkQuestion.order)
        )
        return existing.id, list(rows.scalars().all()), False

    assignment = await hw.create_assignment(
        db=db, teacher_id=teacher.id, school_id=school.id,
        req=CreateAssignmentRequest(
            grade_level=grade_level, subject=subject, chapter=chapter,
            lesson_id=lesson_id, title=title, description=description,
            due_at=datetime.now(tz=timezone.utc) + timedelta(days=due_in_days),
        ),
    )
    question_ids = [
        (await hw.add_question(
            db=db, teacher_id=teacher.id, school_id=school.id,
            assignment_id=assignment.id, req=request,
        )).id
        for request in questions
    ]
    await hw.distribute_assignment(
        db=db, teacher_id=teacher.id, school_id=school.id,
        assignment_id=assignment.id, req=DistributeRequest(),
    )
    return assignment.id, question_ids, True


async def student_assignment_id(
    db: AsyncSession, student: User, school: School, assignment_id: uuid.UUID,
) -> uuid.UUID:
    rows = await hw.list_student_assignments(db=db, student_id=student.id, school_id=school.id)
    return next(row.id for row in rows if row.assignment_id == assignment_id)


def answers_for(questions: list[tuple[uuid.UUID, AddQuestionRequest]], correct: bool) -> list[AnswerInput]:
    """Alternate right and wrong answers so the teacher's list is not uniform."""
    out = []
    for index, (question_id, request) in enumerate(questions):
        if request.format == "short_note":
            out.append(AnswerInput(question_id=question_id, answer=SHORT_NOTE_ANSWER))
            continue
        option_ids = [option.id for option in request.options]
        wrong = next(option for option in option_ids if option != request.correct_answer)
        picked = request.correct_answer if correct or index % 2 == 0 else wrong
        out.append(AnswerInput(question_id=question_id, answer=picked))
    return out


async def simulate_submission(
    db: AsyncSession, student: User, school: School, assignment_id: uuid.UUID,
    questions: list[tuple[uuid.UUID, AddQuestionRequest]], reveal_hints: int = 0,
) -> uuid.UUID:
    sa_id = await student_assignment_id(db, student, school, assignment_id)
    for _ in range(reveal_hints):
        await hw.reveal_hint(
            db=db, student_id=student.id, school_id=school.id,
            student_assignment_id=sa_id, question_id=questions[0][0],
        )
    await hw.submit_homework(
        db=db, student_id=student.id, school_id=school.id,
        student_assignment_id=sa_id, answers=answers_for(questions, correct=False),
    )
    return sa_id


async def simulate_grading(
    db: AsyncSession, teacher: User, school: School, assignment_id: uuid.UUID,
    student_assignment_id_: uuid.UUID, questions: list[tuple[uuid.UUID, AddQuestionRequest]],
    approve: bool,
) -> None:
    await hw.grade_submission(
        db=db, teacher_id=teacher.id, school_id=school.id, assignment_id=assignment_id,
        student_assignment_id=student_assignment_id_,
        req=GradeSubmissionRequest(
            approve=approve,
            grades=[
                GradeAnswerInput(
                    question_id=question_id,
                    score=1.0 if index % 2 == 0 else 0.5,
                    comment="Clear reasoning." if index % 2 == 0 else "Show the middle step.",
                )
                for index, (question_id, _) in enumerate(questions)
            ],
        ),
    )


async def seed() -> None:
    catalog = catalog_seed()
    async with AsyncSessionLocal() as db:
        await seed_catalog(db)
        if "--catalog-only" in sys.argv:
            print(f"Catalog seed complete: {len(catalog['lessons'])} lessons (existing rows preserved).")
            return

        school = await ensure_school(db)
        teachers = [
            await ensure_user(db, school, email, name, UserRole.TEACHER, None, TEACHER_PASSWORD)
            for email, name in TEACHERS
        ]
        roster = {
            grade: [
                await ensure_user(db, school, email, name, UserRole.STUDENT, grade, STUDENT_PASSWORD)
                for email, name in members
            ]
            for grade, members in STUDENTS.items()
        }

        # Chapters in catalog order, so each grade receives the same set of sets.
        chapters = [
            (chapter["id"], lesson)
            for chapter in catalog["chapters"]
            for lesson in [next(
                row for row in catalog["lessons"] if row["chapter_id"] == chapter["id"]
            )]
        ]
        created_total = 0

        for grade, students in roster.items():
            teacher = teachers[0]
            for offset, (chapter_id, lesson) in enumerate(chapters):
                content = lesson["content"]["en"]
                requests = question_requests(catalog, chapter_id)
                assignment_id, question_ids, created = await ensure_assignment(
                    db, teacher, school, grade,
                    subject=content["subject"], chapter=content["chapter"],
                    lesson_id=lesson["id"],
                    title=f"{content['chapter']} practice set",
                    description=content["objective"],
                    due_in_days=3 + offset * 2,
                    questions=requests,
                )
                created_total += int(created)
                questions = list(zip(question_ids, requests))
                if not created:
                    continue

                if chapter_id == SUBMITTED_CHAPTER:
                    # One submission left unmarked, so the teacher has something to grade.
                    await simulate_submission(
                        db, students[0], school, assignment_id, questions, reveal_hints=2,
                    )
                elif chapter_id == GRADED_CHAPTER:
                    # Graded-and-approved beside graded-but-not-approved: the second
                    # student must still see no score until the teacher approves.
                    approved = await simulate_submission(db, students[0], school, assignment_id, questions)
                    await simulate_grading(db, teacher, school, assignment_id, approved, questions, approve=True)
                    withheld = await simulate_submission(db, students[1], school, assignment_id, questions)
                    await simulate_grading(db, teacher, school, assignment_id, withheld, questions, approve=False)

            # A cross-chapter revision set, owned by the second teacher so the
            # teacher-scoped assignment list is exercised by more than one account.
            revision = [
                question_requests(catalog, chapter_id)[0].model_copy(update={"order": order})
                for order, (chapter_id, _) in enumerate(chapters)
            ]
            _, _, created = await ensure_assignment(
                db, teachers[1], school, grade,
                subject="Mixed review", chapter="All chapters",
                lesson_id=chapters[0][1]["id"],
                title="Term revision",
                description="One question from every chapter covered so far.",
                due_in_days=14, questions=revision,
            )
            created_total += int(created)

        await report(db, school, teachers, roster, created_total, catalog)


async def report(
    db: AsyncSession, school: School, teachers: list[User],
    roster: dict[str, list[User]], created_total: int, catalog: dict,
) -> None:
    print("\n--- Seed complete ---")
    print(f"School:   {school.name} ({school.id})")
    print(f"Catalog:  {len(catalog['lessons'])} lessons across "
          f"{len(catalog['subjects'])} subjects")
    print(f"Created:  {created_total} new assignments this run")
    for teacher in teachers:
        print(f"Teacher:  {teacher.email} / {TEACHER_PASSWORD}")
    print()
    for grade, students in roster.items():
        for student in students:
            rows = await hw.list_student_assignments(
                db=db, student_id=student.id, school_id=school.id,
            )
            states = ", ".join(sorted({row.status for row in rows})) or "NONE"
            print(f"Student:  {student.email} / {STUDENT_PASSWORD}  [{grade}]  "
                  f"{len(rows)} assignments ({states})")


if __name__ == "__main__":
    asyncio.run(seed())
