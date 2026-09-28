"""Development seed with teacher-owned classes and varied review evidence."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.class_group import ClassEnrollment, ClassGroup
from app.models.review import MasteryRecord, ReviewAttempt, ReviewLesson, ReviewSession, ReviewSessionSummary
from app.models.school import School
from app.models.user import User, UserRole
from app.services.review_catalog import seed_catalog

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
STUDENT_PASSWORD = "student123"
TEACHER_PASSWORD = "teacher123"

REVIEW_SPECS = {
    "newton-third-law": ("action-reaction", "force-pairs", "force_pair_unequal_magnitude",
                         "The larger object pushes harder", "The forces are equal and opposite on different objects"),
    "balanced-forces": ("net-force", "balanced-forces-check", "balanced_force_means_stopped",
                        "Balanced forces mean the object must stop", "Balanced forces give zero net force"),
    "kinetic-energy": ("kinetic-energy", "kinetic-energy-check", "kinetic_energy_requires_motion",
                       "A stationary object has kinetic energy", "Kinetic energy requires motion"),
    "equivalent-fractions": ("equivalent-fractions", "equivalent-fractions-check",
                             "equivalent_fraction_denominator_only", "Only change the denominator",
                             "Multiply numerator and denominator by the same number"),
}


def completed_state(assisted: bool, attempts: int) -> dict:
    return {
        "index": 0, "attempts": attempts, "hint_level": int(assisted), "assistance": assisted,
        "resolved": True, "complete": True, "events": [], "requests": [],
    }


async def add_review(db, school, student, lesson_id: str, score: float, assisted: bool, days_ago: int):
    lesson = await db.get(ReviewLesson, lesson_id)
    concept, question, error, incorrect, correct = REVIEW_SPECS[lesson_id]
    completed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    attempts = 2 if score >= 0.75 else 1
    session = ReviewSession(
        school_id=school.id, student_id=student.id, lesson_id=lesson.id, content=lesson.content,
        state=completed_state(assisted, attempts), version=attempts + 1,
    )
    db.add(session)
    await db.flush()
    rows = []
    if attempts == 2:
        rows.append(ReviewAttempt(
            school_id=school.id, student_id=student.id, session_id=session.id, lesson_id=lesson.id,
            request_id=uuid.uuid4(), question_id=question, concept_ref=concept, response_text=incorrect,
            correctness_score=0, error_type=error, hint_level=0, assisted=False, attempt_number=1,
            locale="en", created_at=completed_at - timedelta(minutes=2),
        ))
    final_error = error if score < 0.75 else None
    rows.append(ReviewAttempt(
        school_id=school.id, student_id=student.id, session_id=session.id, lesson_id=lesson.id,
        request_id=uuid.uuid4(), question_id=question, concept_ref=concept,
        response_text=correct if score >= 0.75 else incorrect, correctness_score=score,
        error_type=final_error, hint_level=int(assisted), assisted=assisted, attempt_number=attempts,
        locale="en", created_at=completed_at,
    ))
    band = "secure" if score >= 0.75 else "developing" if score >= 0.5 else "needs_support"
    db.add_all([
        *rows,
        MasteryRecord(
            school_id=school.id, student_id=student.id, subject_id=lesson.content["subject_id"],
            concept_ref=concept, mastery_score=score, mastery_band=band, evidence_count=1,
            attempt_count=attempts, assisted_evidence_count=int(assisted),
            dominant_error_type=error if attempts == 2 or final_error else None,
            calculation_version="mvp-v1", last_attempt_at=completed_at,
        ),
        ReviewSessionSummary(
            school_id=school.id, student_id=student.id, session_id=session.id, lesson_id=lesson.id,
            concepts=[{"concept_ref": concept, "mastery_band": band, "completed_with_support": assisted}],
            total_attempts=attempts, calculation_version="mvp-v1", completed_at=completed_at,
        ),
    ])


async def seed():
    async with AsyncSessionLocal() as db:
        await seed_catalog(db)
        if "--catalog-only" in sys.argv:
            print("Catalog seed complete (existing rows preserved).")
            return
        school = School(id=uuid.uuid4(), name="Al-Noor Academy")
        db.add(school)
        await db.flush()
        teachers = {
            "ahmed": User(school_id=school.id, email="teacher@alnoor.edu.sa", full_name="Ahmed Al-Rashid",
                          role=UserRole.TEACHER, hashed_password=hash_password(TEACHER_PASSWORD)),
            "noura": User(school_id=school.id, email="noura.teacher@alnoor.edu.sa", full_name="Noura Al-Harbi",
                          role=UserRole.TEACHER, hashed_password=hash_password(TEACHER_PASSWORD)),
        }
        student_names = {
            "sara": "Sara Al-Otaibi", "omar": "Omar Al-Qahtani", "layla": "Layla Hassan",
            "youssef": "Youssef Mahmoud", "noor": "Noor Al-Salem", "mariam": "Mariam Khaled",
        }
        students = {
            key: User(
                school_id=school.id,
                email="student@alnoor.edu.sa" if key == "sara" else f"{key}@alnoor.edu.sa",
                full_name=name, role=UserRole.STUDENT, hashed_password=hash_password(STUDENT_PASSWORD),
            )
            for key, name in student_names.items()
        }
        db.add_all([*teachers.values(), *students.values()])
        await db.flush()
        classes = {
            "physics_a": ClassGroup(
                school_id=school.id, teacher_id=teachers["ahmed"].id, name="Grade 10 Physics A",
                grade_level="Grade 10", subject_id="physics", academic_year="2026-2027"),
            "math_a": ClassGroup(
                school_id=school.id, teacher_id=teachers["ahmed"].id, name="Grade 10 Mathematics A",
                grade_level="Grade 10", subject_id="mathematics", academic_year="2026-2027"),
            "physics_b": ClassGroup(
                school_id=school.id, teacher_id=teachers["noura"].id, name="Grade 9 Physics B",
                grade_level="Grade 9", subject_id="physics", academic_year="2026-2027"),
        }
        db.add_all(classes.values())
        await db.flush()
        enrollment_map = {
            "physics_a": ["sara", "omar", "layla", "youssef", "noor"],
            "math_a": ["sara", "omar", "mariam"],
            "physics_b": ["mariam"],
        }
        db.add_all(
            ClassEnrollment(school_id=school.id, class_group_id=classes[class_key].id,
                            student_id=students[student_key].id)
            for class_key, student_keys in enrollment_map.items() for student_key in student_keys
        )
        await db.flush()
        reviews = [
            ("sara", "newton-third-law", 1.0, True, 1),
            ("omar", "newton-third-law", 0.25, True, 2),
            ("layla", "newton-third-law", 1.0, False, 3),
            ("youssef", "newton-third-law", 0.6, False, 4),
            ("sara", "kinetic-energy", 0.7, True, 7),
            ("omar", "balanced-forces", 0.5, True, 8),
            ("sara", "equivalent-fractions", 1.0, False, 5),
            ("omar", "equivalent-fractions", 0.55, True, 6),
            ("mariam", "equivalent-fractions", 0.2, True, 9),
        ]
        for review in reviews:
            student_key, lesson_id, score, assisted, days_ago = review
            await add_review(db, school, students[student_key], lesson_id, score, assisted, days_ago)
        await db.commit()
        print("\n--- Seed complete ---")
        print(f"School:   {school.name}")
        print(f"Teachers: {len(teachers)} (password: {TEACHER_PASSWORD})")
        print(f"Students: {len(students)} (password: {STUDENT_PASSWORD})")
        print(f"Classes:  {len(classes)} across Physics and Mathematics")
        print(f"Reviews:  {len(reviews)} across four lessons")
        print("Primary teacher: teacher@alnoor.edu.sa")
        print("Primary student: student@alnoor.edu.sa")


if __name__ == "__main__":
    asyncio.run(seed())
