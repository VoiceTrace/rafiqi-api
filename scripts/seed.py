"""
Development seed script — creates one school, one teacher, one student.
Run with: python scripts/seed.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import settings
from app.services.review_catalog import seed_catalog
from app.core.security import hash_password
from app.models.school import School
from app.models.user import User, UserRole
from app.models.resources import TeacherClass, TeacherClassStudent, TeacherResource, LessonMaterial
import uuid

engine = create_async_engine(settings.DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def seed():
    async with AsyncSessionLocal() as db:
        await seed_catalog(db)
        if "--catalog-only" in sys.argv:
            print("Catalog seed complete (existing rows preserved).")
            return
        school = await db.scalar(select(School).where(School.name == "Al-Noor Academy"))
        if school is None:
            school = School(id=uuid.uuid4(), name="Al-Noor Academy")
            db.add(school)
            await db.flush()

        teacher = await db.scalar(select(User).where(User.email == "teacher@alnoor.edu.sa"))
        if teacher is None:
            teacher = User(id=uuid.uuid4(), school_id=school.id, email="teacher@alnoor.edu.sa",
                full_name="Ahmed Al-Rashid", role=UserRole.TEACHER, hashed_password=hash_password("teacher123"))
            db.add(teacher)
            await db.flush()

        student = await db.scalar(select(User).where(User.email == "student@alnoor.edu.sa"))
        if student is None:
            student = User(id=uuid.uuid4(), school_id=school.id, email="student@alnoor.edu.sa",
                full_name="Sara Al-Otaibi", role=UserRole.STUDENT, hashed_password=hash_password("student123"))
            db.add(student)
            await db.flush()

        classroom = await db.scalar(select(TeacherClass).where(TeacherClass.school_id == school.id,
            TeacherClass.teacher_id == teacher.id, TeacherClass.name == "Grade 10 Physics"))
        if classroom is None:
            classroom = TeacherClass(school_id=school.id, teacher_id=teacher.id, grade_id="grade-10", name="Grade 10 Physics")
            db.add(classroom)
            await db.flush()

        membership = await db.scalar(select(TeacherClassStudent).where(TeacherClassStudent.class_id == classroom.id,
            TeacherClassStudent.student_id == student.id))
        if membership is None:
            db.add(TeacherClassStudent(school_id=school.id, class_id=classroom.id, student_id=student.id))

        resource = await db.scalar(select(TeacherResource).where(TeacherResource.school_id == school.id,
            TeacherResource.created_by == teacher.id, TeacherResource.title == "Newton’s Third Law: Action and Reaction"))
        if resource is None:
            resource = TeacherResource(school_id=school.id, created_by=teacher.id, type="article",
                title="Newton’s Third Law: Action and Reaction",
                description="For every action force, an equal and opposite reaction force acts on a different object.",
                source_url="https://www.khanacademy.org/science/physics/forces-newtons-laws")
            db.add(resource)
            await db.flush()

        assignment = await db.scalar(select(LessonMaterial).where(LessonMaterial.school_id == school.id,
            LessonMaterial.class_id == classroom.id, LessonMaterial.resource_id == resource.id,
            LessonMaterial.lesson_id == "newton-third-law"))
        if assignment is None:
            db.add(LessonMaterial(school_id=school.id, class_id=classroom.id, resource_id=resource.id,
                lesson_id="newton-third-law", required=True, added_by=teacher.id))
        await db.commit()

        print("\n--- Seed complete ---")
        print(f"School:  {school.name} ({school.id})")
        print(f"Teacher: {teacher.email} / teacher123")
        print(f"Student: {student.email} / student123")
        print(f"Sample class: {classroom.name} (Grade 10)")
        print(f"Assigned resource: {resource.title} -> Newton's Third Law")


if __name__ == "__main__":
    asyncio.run(seed())
