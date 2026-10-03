import uuid
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.review import ReviewGrade, ReviewLesson, ReviewLessonGrade, ReviewChapter, ReviewSubject
from app.models.resources import TeacherClass, TeacherClassStudent, TeacherResource, LessonMaterial, MaterialCompletion
from app.models.user import User, UserRole
from app.services.notifications import enqueue_assignment_event


class ResourceError(Exception):
    def __init__(self, code: str, status: int = 404):
        self.code, self.status = code, status


async def list_grades(db: AsyncSession, locale: str):
    rows = (await db.execute(select(ReviewGrade).order_by(ReviewGrade.id))).scalars().all()
    return [{"id": r.id, "title": r.title.get(locale, "")} for r in rows]


async def list_grade_curriculum(db: AsyncSession, grade_id: str, locale: str):
    if await db.get(ReviewGrade, grade_id) is None:
        raise ResourceError("grade_not_found")
    query = (select(ReviewLesson, ReviewChapter, ReviewSubject)
        .join(ReviewChapter, ReviewLesson.chapter_id == ReviewChapter.id)
        .join(ReviewSubject, ReviewChapter.subject_id == ReviewSubject.id)
        .join(ReviewLessonGrade, ReviewLessonGrade.lesson_id == ReviewLesson.id)
        .where(ReviewLessonGrade.grade_id == grade_id).order_by(ReviewSubject.id, ReviewChapter.id, ReviewLesson.id))
    rows = (await db.execute(query)).all()
    return [{"id": lesson.id, "title": lesson.content[locale]["title"], "chapter_id": chapter.id,
        "chapter": chapter.title[locale], "subject_id": subject.id, "subject": subject.title[locale], "grade_id": grade_id}
        for lesson, chapter, subject in rows]


async def list_classes(db, school_id, teacher_id, locale):
    query = (select(TeacherClass, ReviewGrade, func.count(TeacherClassStudent.id))
        .join(ReviewGrade, ReviewGrade.id == TeacherClass.grade_id)
        .outerjoin(TeacherClassStudent, TeacherClassStudent.class_id == TeacherClass.id)
        .where(TeacherClass.school_id == school_id, TeacherClass.teacher_id == teacher_id)
        .group_by(TeacherClass.id, ReviewGrade.id).order_by(TeacherClass.name))
    return [{"id": c.id, "name": c.name, "grade_id": c.grade_id, "grade_title": grade.title[locale], "student_count": count}
        for c, grade, count in (await db.execute(query)).all()]


async def create_class(db, school_id, teacher_id, name, grade_id):
    if await db.get(ReviewGrade, grade_id) is None:
        raise ResourceError("grade_not_found", 422)
    row = TeacherClass(school_id=school_id, teacher_id=teacher_id, name=name.strip(), grade_id=grade_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_students(db, school_id, teacher_id, class_id):
    if await db.scalar(select(TeacherClass.id).where(TeacherClass.id == class_id, TeacherClass.school_id == school_id, TeacherClass.teacher_id == teacher_id)) is None:
        raise ResourceError("class_not_found")
    query = (select(User.id, User.full_name, User.email).join(TeacherClassStudent, TeacherClassStudent.student_id == User.id)
        .where(TeacherClassStudent.class_id == class_id, TeacherClassStudent.school_id == school_id, User.school_id == school_id, User.role == UserRole.STUDENT)
        .order_by(User.full_name))
    return [{"id": row.id, "full_name": row.full_name, "email": row.email} for row in (await db.execute(query)).all()]


async def add_student(db, school_id, teacher_id, class_id, student_id):
    cls = await db.scalar(select(TeacherClass).where(TeacherClass.id == class_id, TeacherClass.school_id == school_id, TeacherClass.teacher_id == teacher_id))
    user = await db.scalar(select(User).where(User.id == student_id, User.school_id == school_id, User.role == UserRole.STUDENT, User.is_active.is_(True)))
    if cls is None: raise ResourceError("class_not_found")
    if user is None: raise ResourceError("student_not_found", 422)
    await db.execute(insert(TeacherClassStudent).values(id=uuid.uuid4(), school_id=school_id, class_id=class_id, student_id=student_id).on_conflict_do_nothing(constraint="uq_class_student"))
    await db.commit()
    return await list_students(db, school_id, teacher_id, class_id)


async def list_resources(db, school_id, teacher_id):
    rows = (await db.execute(select(TeacherResource).where(TeacherResource.school_id == school_id, TeacherResource.created_by == teacher_id, TeacherResource.archived_at.is_(None)).order_by(TeacherResource.created_at.desc()))).scalars().all()
    assignments = (await db.execute(select(LessonMaterial.resource_id, TeacherClass.id)
        .join(TeacherClass, TeacherClass.id == LessonMaterial.class_id)
        .where(LessonMaterial.school_id == school_id, TeacherClass.school_id == school_id, TeacherClass.teacher_id == teacher_id))).all()
    assigned_classes: dict[uuid.UUID, set[uuid.UUID]] = {}
    for resource_id, class_id in assignments:
        assigned_classes.setdefault(resource_id, set()).add(class_id)
    return [{
        "id": row.id, "type": row.type, "title": row.title, "description": row.description,
        "question": row.question, "answer": row.answer, "source_url": row.source_url,
        "original_filename": row.original_filename, "media_type": row.media_type,
        "byte_size": row.byte_size, "created_at": row.created_at,
        "assigned_class_ids": sorted(assigned_classes.get(row.id, set()), key=str),
    } for row in rows]


async def create_resource(db, school_id, teacher_id, body):
    if body.type == "question" and (not body.question or not body.answer):
        raise ResourceError("question_and_answer_required", 422)
    if body.type == "link" and not body.source_url:
        raise ResourceError("source_url_required", 422)
    if body.type in {"image", "video", "file"}:
        raise ResourceError("validated_upload_required", 422)
    row = TeacherResource(school_id=school_id, created_by=teacher_id, type=body.type, title=body.title.strip(),
        description=body.description.strip(), question=body.question, answer=body.answer,
        source_url=str(body.source_url) if body.source_url else None)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def create_uploaded_resource(db, school_id, teacher_id, title, description, upload):
    allowed = {".pdf": ("application/pdf", b"%PDF-"), ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
        ".jpg": ("image/jpeg", b"\xff\xd8\xff"), ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
        ".webp": ("image/webp", b"RIFF"), ".mp4": ("video/mp4", b""), ".webm": ("video/webm", b"\x1aE\xdf\xa3")}
    name = Path((upload.filename or "").replace("\\", "/")).name
    ext = Path(name).suffix.lower()
    if ext not in allowed: raise ResourceError("unsupported_upload_type", 422)
    if upload.size is not None and upload.size > 20 * 1024 * 1024: raise ResourceError("upload_size_invalid", 422)
    content = await upload.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024: raise ResourceError("upload_size_invalid", 422)
    mime, signature = allowed[ext]
    if upload.content_type != mime: raise ResourceError("upload_type_mismatch", 422)
    if signature and not content.startswith(signature): raise ResourceError("invalid_upload_content", 422)
    if ext == ".webp" and content[8:12] != b"WEBP": raise ResourceError("invalid_upload_content", 422)
    if ext == ".mp4" and b"ftyp" not in content[4:12]: raise ResourceError("invalid_upload_content", 422)
    token = uuid.uuid4().hex
    directory = Path(settings.RESOURCE_STORAGE_DIR) / str(school_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{token}{ext}").write_bytes(content)
    kind = "image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "file"
    row = TeacherResource(school_id=school_id, created_by=teacher_id, type=kind, title=title.strip() or name,
        description=description.strip(), storage_name=f"{school_id}/{token}{ext}", original_filename=name[:255], media_type=mime, byte_size=len(content))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def create_assignment(db, school_id, teacher_id, class_id, lesson_id, resource_id, required):
    cls = await db.scalar(select(TeacherClass).where(TeacherClass.id == class_id, TeacherClass.school_id == school_id, TeacherClass.teacher_id == teacher_id))
    resource = await db.scalar(select(TeacherResource).where(TeacherResource.id == resource_id, TeacherResource.school_id == school_id, TeacherResource.created_by == teacher_id, TeacherResource.archived_at.is_(None)))
    valid = await db.scalar(select(ReviewLessonGrade.lesson_id).where(ReviewLessonGrade.lesson_id == lesson_id, ReviewLessonGrade.grade_id == cls.grade_id)) if cls else None
    if cls is None: raise ResourceError("class_not_found")
    if resource is None: raise ResourceError("resource_not_found")
    if valid is None: raise ResourceError("lesson_not_in_class_grade", 422)
    existing = await db.scalar(select(LessonMaterial).where(LessonMaterial.school_id == school_id, LessonMaterial.class_id == class_id, LessonMaterial.resource_id == resource_id, LessonMaterial.lesson_id == lesson_id))
    if existing:
        existing.required = required
        row = existing
    else:
        row = LessonMaterial(school_id=school_id, class_id=class_id, resource_id=resource_id, lesson_id=lesson_id, required=required, added_by=teacher_id)
        db.add(row)
        await db.flush()
        await enqueue_assignment_event(db, school_id, row.id)
    await db.commit()
    await db.refresh(row)
    return row


async def list_student_materials(db, school_id, student_id, lesson_id, locale):
    query = (select(LessonMaterial, TeacherResource, MaterialCompletion.completed)
        .join(TeacherClassStudent, TeacherClassStudent.class_id == LessonMaterial.class_id)
        .join(TeacherResource, TeacherResource.id == LessonMaterial.resource_id)
        .outerjoin(MaterialCompletion, (MaterialCompletion.lesson_material_id == LessonMaterial.id) & (MaterialCompletion.student_id == student_id) & (MaterialCompletion.school_id == school_id))
        .where(LessonMaterial.school_id == school_id, TeacherClassStudent.school_id == school_id, TeacherClassStudent.student_id == student_id,
            LessonMaterial.lesson_id == lesson_id, TeacherResource.archived_at.is_(None)).order_by(LessonMaterial.created_at))
    rows = (await db.execute(query)).all()
    return [{"id": assignment.id, "lesson_id": assignment.lesson_id, "type": resource.type, "title": resource.title,
        "description": resource.description, "question": resource.question, "source_url": resource.source_url,
        "download_url": f"/study-materials/{assignment.id}/download" if resource.storage_name else None,
        "original_filename": resource.original_filename, "media_type": resource.media_type, "byte_size": resource.byte_size,
        "required": assignment.required, "completed": bool(completed)} for assignment, resource, completed in rows]


async def list_student_resources(db, school_id, student_id, locale):
    query = (select(LessonMaterial, TeacherResource, MaterialCompletion.completed, TeacherClass, ReviewGrade,
                    ReviewLesson, ReviewChapter, ReviewSubject)
        .join(TeacherClassStudent, TeacherClassStudent.class_id == LessonMaterial.class_id)
        .join(TeacherClass, TeacherClass.id == LessonMaterial.class_id)
        .join(ReviewGrade, ReviewGrade.id == TeacherClass.grade_id)
        .join(TeacherResource, TeacherResource.id == LessonMaterial.resource_id)
        .join(ReviewLesson, ReviewLesson.id == LessonMaterial.lesson_id)
        .join(ReviewChapter, ReviewChapter.id == ReviewLesson.chapter_id)
        .join(ReviewSubject, ReviewSubject.id == ReviewChapter.subject_id)
        .outerjoin(MaterialCompletion, (MaterialCompletion.lesson_material_id == LessonMaterial.id) &
                   (MaterialCompletion.student_id == student_id) & (MaterialCompletion.school_id == school_id))
        .where(LessonMaterial.school_id == school_id, TeacherClassStudent.school_id == school_id,
               TeacherClassStudent.student_id == student_id, TeacherClass.school_id == school_id,
               TeacherResource.school_id == school_id, TeacherResource.archived_at.is_(None))
        .order_by(ReviewSubject.id, ReviewChapter.id, ReviewLesson.id, TeacherClass.name, LessonMaterial.created_at))
    rows = (await db.execute(query)).all()
    result = []
    for assignment, resource, completed, class_row, grade, lesson, chapter, subject in rows:
        lesson_content = lesson.content.get(locale, lesson.content.get("en", {}))
        result.append({
            "id": assignment.id, "lesson_id": lesson.id, "type": resource.type, "title": resource.title,
            "description": resource.description, "question": resource.question, "source_url": resource.source_url,
            "download_url": f"/study-materials/{assignment.id}/download" if resource.storage_name else None,
            "original_filename": resource.original_filename, "media_type": resource.media_type,
            "byte_size": resource.byte_size, "required": assignment.required, "completed": bool(completed),
            "grade_id": grade.id, "grade_title": grade.title.get(locale, grade.title.get("en", "")),
            "class_id": class_row.id, "class_name": class_row.name,
            "subject_id": subject.id, "subject_title": subject.title.get(locale, subject.title.get("en", "")),
            "chapter_id": chapter.id, "chapter_title": chapter.title.get(locale, chapter.title.get("en", "")),
            "lesson_title": lesson_content.get("title", lesson.id),
        })
    return result


async def set_completion(db, school_id, student_id, lesson_id, assignment_id, completed):
    assignment = await db.scalar(select(LessonMaterial).join(TeacherClassStudent, TeacherClassStudent.class_id == LessonMaterial.class_id)
        .where(LessonMaterial.id == assignment_id, LessonMaterial.lesson_id == lesson_id, LessonMaterial.school_id == school_id,
            TeacherClassStudent.school_id == school_id, TeacherClassStudent.student_id == student_id))
    if assignment is None: raise ResourceError("material_not_found")
    statement = insert(MaterialCompletion).values(id=uuid.uuid4(), school_id=school_id, student_id=student_id,
        lesson_material_id=assignment_id, completed=completed).on_conflict_do_update(
        constraint="uq_student_material_completion", set_={"completed": completed, "updated_at": func.now()})
    await db.execute(statement)
    row = await db.scalar(select(MaterialCompletion).where(MaterialCompletion.school_id == school_id,
        MaterialCompletion.student_id == student_id, MaterialCompletion.lesson_material_id == assignment_id))
    await db.commit()
    await db.refresh(row)
    return {"assignment_id": assignment_id, "completed": row.completed, "updated_at": row.updated_at}


async def get_download(db, school_id, user_id, user_role, assignment_id):
    query = select(TeacherResource).join(LessonMaterial, LessonMaterial.resource_id == TeacherResource.id).where(
        LessonMaterial.id == assignment_id, LessonMaterial.school_id == school_id, TeacherResource.school_id == school_id,
        TeacherResource.archived_at.is_(None))
    if user_role == UserRole.STUDENT:
        query = query.join(TeacherClassStudent, TeacherClassStudent.class_id == LessonMaterial.class_id).where(TeacherClassStudent.student_id == user_id, TeacherClassStudent.school_id == school_id)
    else:
        query = query.join(TeacherClass, TeacherClass.id == LessonMaterial.class_id).where(TeacherClass.teacher_id == user_id)
    return await db.scalar(query)


async def get_library_resource_download(db, school_id, teacher_id, resource_id):
    """Return an uploaded library asset only to its owner within the same school."""
    return await db.scalar(select(TeacherResource).where(
        TeacherResource.id == resource_id,
        TeacherResource.school_id == school_id,
        TeacherResource.created_by == teacher_id,
        TeacherResource.archived_at.is_(None),
        TeacherResource.storage_name.is_not(None),
    ))
