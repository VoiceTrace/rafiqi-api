"""
Development seed script — creates one school, one teacher, one student.
Run with: python scripts/seed.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import settings
from app.services.review_catalog import seed_catalog
from app.core.security import hash_password
from app.models.school import School
from app.models.user import User, UserRole
from app.models.class_group import ClassEnrollment, ClassGroup
import uuid
from datetime import datetime, timezone

from app.models.review import MasteryRecord, ReviewAttempt, ReviewLesson, ReviewSession, ReviewSessionSummary

engine = create_async_engine(settings.DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def seed():
    async with AsyncSessionLocal() as db:
        await seed_catalog(db)
        if "--catalog-only" in sys.argv:
            print("Catalog seed complete (existing rows preserved).")
            return
        # School
        school = School(id=uuid.uuid4(), name="Al-Noor Academy")
        db.add(school)
        await db.flush()

        # Teacher
        teacher = User(
            id=uuid.uuid4(),
            school_id=school.id,
            email="teacher@alnoor.edu.sa",
            full_name="Ahmed Al-Rashid",
            role=UserRole.TEACHER,
            hashed_password=hash_password("teacher123"),
        )

        # Student
        student = User(
            id=uuid.uuid4(),
            school_id=school.id,
            email="student@alnoor.edu.sa",
            full_name="Sara Al-Otaibi",
            role=UserRole.STUDENT,
            hashed_password=hash_password("student123"),
        )

        db.add_all([teacher, student])
        await db.flush()

        class_group = ClassGroup(
            id=uuid.uuid4(),
            school_id=school.id,
            teacher_id=teacher.id,
            name="Grade 10 Physics A",
            grade_level="Grade 10",
            subject_id="physics",
            academic_year="2026-2027",
        )
        db.add(class_group)
        await db.flush()
        db.add(
            ClassEnrollment(
                id=uuid.uuid4(),
                school_id=school.id,
                class_group_id=class_group.id,
                student_id=student.id,
            )
        )
        await db.flush()

        lesson = await db.get(ReviewLesson, "newton-third-law")
        completed_at = datetime.now(timezone.utc)
        review_session = ReviewSession(
            id=uuid.uuid4(),
            school_id=school.id,
            student_id=student.id,
            lesson_id=lesson.id,
            content=lesson.content,
            state={
                "index": 0,
                "attempts": 3,
                "hint_level": 1,
                "assistance": True,
                "resolved": True,
                "complete": True,
                "events": [],
                "requests": [],
            },
            version=4,
        )
        db.add(review_session)
        await db.flush()
        db.add_all(
            [
                ReviewAttempt(
                    school_id=school.id, student_id=student.id, session_id=review_session.id,
                    lesson_id=lesson.id, request_id=uuid.uuid4(), question_id="force-pairs",
                    concept_ref="action-reaction", response_text="A smaller force backward",
                    option_id="smaller", correctness_score=0, error_type="force_pair_unequal_magnitude",
                    hint_level=0, assisted=False, attempt_number=1, locale="en", created_at=completed_at,
                ),
                ReviewAttempt(
                    school_id=school.id, student_id=student.id, session_id=review_session.id,
                    lesson_id=lesson.id, request_id=uuid.uuid4(), question_id="force-pairs",
                    concept_ref="action-reaction", response_text="An equal force backward",
                    option_id="equal", correctness_score=1, error_type=None,
                    hint_level=1, assisted=True, attempt_number=2, locale="en", created_at=completed_at,
                ),
                ReviewAttempt(
                    school_id=school.id, student_id=student.id, session_id=review_session.id,
                    lesson_id=lesson.id, request_id=uuid.uuid4(), question_id="different-objects",
                    concept_ref="action-reaction", response_text="They act on different objects",
                    option_id=None, correctness_score=1, error_type=None,
                    hint_level=0, assisted=False, attempt_number=1, locale="en", created_at=completed_at,
                ),
                MasteryRecord(
                    school_id=school.id, student_id=student.id, subject_id="physics",
                    concept_ref="action-reaction", mastery_score=1, mastery_band="secure",
                    evidence_count=2, attempt_count=3, assisted_evidence_count=1,
                    dominant_error_type="force_pair_unequal_magnitude", calculation_version="mvp-v1",
                    last_attempt_at=completed_at,
                ),
                ReviewSessionSummary(
                    school_id=school.id, student_id=student.id, session_id=review_session.id,
                    lesson_id=lesson.id,
                    concepts=[{"concept_ref": "action-reaction", "outcome": "secure", "completed_with_support": True}],
                    total_attempts=3, calculation_version="mvp-v1", completed_at=completed_at,
                ),
            ]
        )
        await db.commit()

        print("\n--- Seed complete ---")
        print(f"School:  {school.name} ({school.id})")
        print(f"Teacher: {teacher.email} / teacher123")
        print(f"Student: {student.email} / student123")
        print(f"Class:   {class_group.name} ({class_group.id})")
        print(f"Review:  {lesson.content['en']['title']} completed ({review_session.id})")


if __name__ == "__main__":
    asyncio.run(seed())
