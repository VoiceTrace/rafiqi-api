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
import uuid

engine = create_async_engine(settings.DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Homework is published to a grade, so seeded students need one to receive any.
GRADE_LEVEL = "Grade 10"


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

        # Student — grade_level is required for homework to reach them, since
        # assignments are distributed to a whole grade rather than named students.
        student = User(
            id=uuid.uuid4(),
            school_id=school.id,
            email="student@alnoor.edu.sa",
            full_name="Sara Al-Otaibi",
            role=UserRole.STUDENT,
            grade_level=GRADE_LEVEL,
            hashed_password=hash_password("student123"),
        )

        # A second student in the same grade, so distribution and the teacher's
        # submissions list are exercised with more than one recipient.
        peer = User(
            id=uuid.uuid4(),
            school_id=school.id,
            email="student2@alnoor.edu.sa",
            full_name="Omar Al-Harbi",
            role=UserRole.STUDENT,
            grade_level=GRADE_LEVEL,
            hashed_password=hash_password("student123"),
        )

        db.add_all([teacher, student, peer])
        await db.commit()

        print("\n--- Seed complete ---")
        print(f"School:  {school.name} ({school.id})")
        print(f"Teacher: {teacher.email} / teacher123")
        print(f"Student: {student.email} / student123  (grade {GRADE_LEVEL})")
        print(f"Student: {peer.email} / student123  (grade {GRADE_LEVEL})")


if __name__ == "__main__":
    asyncio.run(seed())
