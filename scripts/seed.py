"""Idempotently seed a rich local demo school and its resource library.

Run migrations first, then: python scripts/seed.py
The demo accounts all use role-specific passwords shown in the completion output.
Use --catalog-only to seed only the shared curriculum catalog.
"""
import asyncio
import base64
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.resources import LessonMaterial, TeacherClass, TeacherClassStudent, TeacherResource
from app.models.review import ReviewLessonGrade
from app.models.school import School
from app.models.user import User, UserRole
from app.services.review_catalog import seed_catalog


engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Tiny demo fixtures whose file signatures match the upload validator. They keep
# the development seed lightweight while exercising each stored media type.
ASSETS = {
    "png": ("action-reaction-diagram.png", "image/png", base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/"
        "fLsAAAAASUVORK5CYII=")),
    "jpg": ("classroom-force-photo.jpg", "image/jpeg", base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
        "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/AP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAQUCcf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8B/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABAf/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPxB//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxB//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxB//9k=")),
    "mp4": ("lesson-introduction.mp4", "video/mp4", b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"),
    "webm": ("motion-demo.webm", "video/webm", b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01"),
    "pdf": ("lesson-worksheet.pdf", "application/pdf", b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"),
}

TEACHERS = [
    ("teacher@alnoor.edu.sa", "Ahmed Al-Rashid"),
    ("teacher2@alnoor.edu.sa", "Mariam Hassan"),
    ("teacher3@alnoor.edu.sa", "Omar Farouk"),
    ("teacher4@alnoor.edu.sa", "Noura Saleh"),
]
STUDENT_NAMES = [
    "Sara Al-Otaibi", "Yousef Al-Harbi", "Lina Mansour", "Khalid Nasser",
    "Reem Adel", "Ziad Ibrahim", "Hana Sami", "Faisal Omar", "Maha Khaled",
    "Tariq Jamal", "Noor Hani", "Rayan Ali", "Jana Mostafa", "Salem Rashid",
    "Layla Fadi", "Amir Tamer", "Dana Hossam", "Bader Saeed", "Yara Wael",
    "Hassan Majed", "Malak Karim", "Anas Rami", "Rana Samir", "Sami Adel",
]
CLASS_SPECS = [
    (0, "Grade 10 Physics - Section A", "grade-10"),
    (0, "Grade 9 Physics - Section A", "grade-9"),
    (0, "Grade 6 Mathematics - Section A", "grade-6"),
    (1, "Grade 11 Physics - Section A", "grade-11"),
    (1, "Grade 8 Physics - Section A", "grade-8"),
    (1, "Grade 7 Mathematics - Section A", "grade-7"),
    (2, "Grade 12 Physics - Section A", "grade-12"),
    (2, "Grade 10 Physics - Section B", "grade-10"),
    (2, "Grade 5 Mathematics - Section A", "grade-5"),
    (3, "Grade 9 Physics - Section B", "grade-9"),
    (3, "Grade 8 Physics - Section B", "grade-8"),
    (3, "Grade 6 Mathematics - Section B", "grade-6"),
]


async def get_or_create_user(db, school_id, email, name, role, password):
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(id=uuid.uuid4(), school_id=school_id, email=email, full_name=name,
            role=role, hashed_password=hash_password(password))
        db.add(user)
        await db.flush()
    return user


async def get_or_create_class(db, school_id, teacher, name, grade_id):
    row = await db.scalar(select(TeacherClass).where(TeacherClass.school_id == school_id,
        TeacherClass.teacher_id == teacher.id, TeacherClass.name == name))
    if row is None:
        row = TeacherClass(school_id=school_id, teacher_id=teacher.id, grade_id=grade_id, name=name)
        db.add(row)
        await db.flush()
    return row


async def get_or_create_resource(db, school_id, teacher, resource_spec, asset_number):
    kind, title, description, source_url, question, answer, asset_key = resource_spec
    row = await db.scalar(select(TeacherResource).where(TeacherResource.school_id == school_id,
        TeacherResource.created_by == teacher.id, TeacherResource.title == title))
    if row is None:
        row = TeacherResource(school_id=school_id, created_by=teacher.id, type=kind, title=title,
            description=description, source_url=source_url, question=question, answer=answer)
    if asset_key:
        filename, media_type, content = ASSETS[asset_key]
        suffix = Path(filename).suffix
        token = f"demo-{teacher.id.hex[:8]}-{asset_number}-{asset_key}"
        storage_name = f"{school_id}/{token}{suffix}"
        destination = Path(settings.RESOURCE_STORAGE_DIR) / storage_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        row.storage_name = storage_name
        row.original_filename = filename
        row.media_type = media_type
        row.byte_size = len(content)
    if row.id is None:
        db.add(row)
        await db.flush()
    return row


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

        teachers = []
        for email, name in TEACHERS:
            teachers.append(await get_or_create_user(db, school.id, email, name, UserRole.TEACHER, "teacher123"))
        students = []
        for index, name in enumerate(STUDENT_NAMES, start=1):
            email = "student@alnoor.edu.sa" if index == 1 else f"student{index}@alnoor.edu.sa"
            students.append(await get_or_create_user(db, school.id, email, name, UserRole.STUDENT, "student123"))

        class_rows = []
        for index, (teacher_index, name, grade_id) in enumerate(CLASS_SPECS):
            teacher = teachers[teacher_index]
            classroom = await get_or_create_class(db, school.id, teacher, name, grade_id)
            class_rows.append((teacher, classroom, grade_id))
            # Each class has eight students; memberships overlap to make class lists realistic.
            for offset in range(8):
                student = students[(index * 3 + offset) % len(students)]
                existing = await db.scalar(select(TeacherClassStudent.id).where(
                    TeacherClassStudent.class_id == classroom.id, TeacherClassStudent.student_id == student.id))
                if existing is None:
                    db.add(TeacherClassStudent(school_id=school.id, class_id=classroom.id, student_id=student.id))

        resource_rows = {}
        for teacher_index, teacher in enumerate(teachers, start=1):
            prefix = f"T{teacher_index}"
            specs = [
                ("question", f"{prefix} Newton's Third Law practice", "Check your understanding of action and reaction forces.", None,
                    "A swimmer pushes water backward. Which way does the water push the swimmer?", "Forward, with an equal and opposite force.", None),
                ("question", f"{prefix} Energy quick check", "A short retrieval question for the lesson.", None,
                    "What happens to kinetic energy when an object's speed increases?", "It increases.", None),
                ("article", f"{prefix} Action and reaction explained", "A concise reading on equal and opposite forces acting on different objects.", None, None, None, None),
                ("article", f"{prefix} Energy in everyday motion", "Examples of kinetic energy in sport, transport, and play.", None, None, None, None),
                ("link", f"{prefix} Physics learning video", "An external lesson reference for independent study.", "https://www.khanacademy.org/science/physics/forces-newtons-laws", None, None, None),
                ("link", f"{prefix} Fraction practice", "Online practice for equivalent fractions.", "https://www.khanacademy.org/math/arithmetic/fraction-arithmetic", None, None, None),
                ("image", f"{prefix} Action-reaction diagram", "A visual example of two objects exerting forces on one another.", None, None, None, "png"),
                ("image", f"{prefix} Classroom force photo", "A small image resource for force-pair discussion.", None, None, None, "jpg"),
                ("video", f"{prefix} Motion lesson clip", "Short demo video resource for a class discussion.", None, None, None, "mp4"),
                ("video", f"{prefix} Motion demo WebM", "WebM video resource for movement and energy examples.", None, None, None, "webm"),
                ("file", f"{prefix} Lesson worksheet PDF", "Printable practice sheet for after class.", None, None, None, "pdf"),
                ("file", f"{prefix} Review handout PDF", "A second downloadable resource for revision.", None, None, None, "pdf"),
            ]
            resource_rows[teacher.id] = []
            for asset_number, spec in enumerate(specs, start=1):
                resource_rows[teacher.id].append(await get_or_create_resource(db, school.id, teacher, spec, asset_number))

        # Give each class a full mix of resource types, assigned only to lessons mapped to its grade.
        for teacher, classroom, grade_id in class_rows:
            lesson_ids = (await db.scalars(select(ReviewLessonGrade.lesson_id)
                .where(ReviewLessonGrade.grade_id == grade_id).order_by(ReviewLessonGrade.lesson_id))).all()
            if not lesson_ids:
                continue
            teacher_resources = resource_rows[teacher.id]
            for resource_index, resource in enumerate(teacher_resources):
                lesson_id = lesson_ids[resource_index % len(lesson_ids)]
                existing = await db.scalar(select(LessonMaterial).where(
                    LessonMaterial.school_id == school.id, LessonMaterial.class_id == classroom.id,
                    LessonMaterial.resource_id == resource.id, LessonMaterial.lesson_id == lesson_id))
                if existing is None:
                    db.add(LessonMaterial(school_id=school.id, class_id=classroom.id, resource_id=resource.id,
                        lesson_id=lesson_id, required=(resource_index % 2 == 0), added_by=teacher.id))

        await db.commit()

        print("\n--- Demo seed complete ---")
        print(f"School: {school.name}")
        print(f"Teachers: {len(teachers)} (teacher@alnoor.edu.sa, teacher2@alnoor.edu.sa, ...)")
        print("Teacher password: teacher123")
        print(f"Students: {len(students)} (student@alnoor.edu.sa, student2@alnoor.edu.sa, ...)")
        print("Student password: student123")
        print(f"Classes: {len(class_rows)} across Grades 5, 6, 7, 8, 9, 10, 11, and 12")
        print(f"Library resources: {sum(len(rows) for rows in resource_rows.values())} across question, article, link, image, video, and file")


if __name__ == "__main__":
    asyncio.run(seed())
