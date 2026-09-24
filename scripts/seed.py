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
        await db.commit()

        print("\n--- Seed complete ---")
        print(f"School:  {school.name} ({school.id})")
        print(f"Teacher: {teacher.email} / teacher123")
        print(f"Student: {student.email} / student123")


if __name__ == "__main__":
    asyncio.run(seed())
