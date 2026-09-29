import uuid
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentUser, get_current_user, get_db_session, require_student, require_teacher
from app.core.config import settings
from app.core.errors import ErrorCode
from app.schemas.resources import AssignmentCreate, ClassCreate, CompletionUpdate, ResourceCreate, ResourceOut
from app.services import resources as svc

router = APIRouter(tags=["teacher-resources"])
Db = Annotated[AsyncSession, Depends(get_db_session)]
Teacher = Annotated[CurrentUser, Depends(require_teacher)]
Student = Annotated[CurrentUser, Depends(require_student)]
Current = Annotated[CurrentUser, Depends(get_current_user)]

def _http(error: svc.ResourceError):
    code = ErrorCode.NOT_FOUND if error.status == 404 else ErrorCode.VALIDATION_ERROR if error.status == 422 else ErrorCode.INTERNAL_ERROR
    return HTTPException(status_code=error.status, detail={"error": {"code": code, "message": error.code}})

@router.get("/teacher/resource-grades")
async def grades(user: Teacher, db: Db, locale: str = "en"):
    return await svc.list_grades(db, locale if locale in ("en", "ar") else "en")

@router.get("/teacher/resource-grades/{grade_id}/lessons")
async def curriculum(grade_id: str, user: Teacher, db: Db, locale: str = "en"):
    try: return await svc.list_grade_curriculum(db, grade_id, locale if locale in ("en", "ar") else "en")
    except svc.ResourceError as error: raise _http(error)

@router.get("/teacher/classes")
async def classes(user: Teacher, db: Db, locale: str = "en"):
    return await svc.list_classes(db, user.school_id, user.id, locale if locale in ("en", "ar") else "en")

@router.post("/teacher/classes", status_code=201)
async def create_class(body: ClassCreate, user: Teacher, db: Db, locale: str = "en"):
    try:
        await svc.create_class(db, user.school_id, user.id, body.name, body.grade_id)
        return await svc.list_classes(db, user.school_id, user.id, locale if locale in ("en", "ar") else "en")
    except svc.ResourceError as error: raise _http(error)

@router.get("/teacher/classes/{class_id}/students")
async def class_students(class_id: uuid.UUID, user: Teacher, db: Db):
    try: return await svc.list_students(db, user.school_id, user.id, class_id)
    except svc.ResourceError as error: raise _http(error)

@router.post("/teacher/classes/{class_id}/students/{student_id}")
async def enroll_student(class_id: uuid.UUID, student_id: uuid.UUID, user: Teacher, db: Db):
    try: return await svc.add_student(db, user.school_id, user.id, class_id, student_id)
    except svc.ResourceError as error: raise _http(error)

@router.get("/teacher/resources", response_model=list[ResourceOut])
async def resources(user: Teacher, db: Db):
    return await svc.list_resources(db, user.school_id, user.id)

@router.post("/teacher/resources", status_code=201, response_model=ResourceOut)
async def create_resource(body: ResourceCreate, user: Teacher, db: Db):
    try: return await svc.create_resource(db, user.school_id, user.id, body)
    except svc.ResourceError as error: raise _http(error)

@router.post("/teacher/resources/upload", status_code=201, response_model=ResourceOut)
async def upload_resource(user: Teacher, db: Db, title: Annotated[str, Form(max_length=240)] = "", description: Annotated[str, Form(max_length=8000)] = "", file: UploadFile = File(...)):
    try: return await svc.create_uploaded_resource(db, user.school_id, user.id, title, description, file)
    except svc.ResourceError as error: raise _http(error)

@router.post("/teacher/lesson-materials", status_code=201)
async def assign(body: AssignmentCreate, user: Teacher, db: Db):
    try: return await svc.create_assignment(db, user.school_id, user.id, body.class_id, body.lesson_id, body.resource_id, body.required)
    except svc.ResourceError as error: raise _http(error)

@router.get("/study-lessons/{lesson_id}/materials")
async def student_materials(lesson_id: str, user: Student, db: Db, locale: str = "en"):
    return await svc.list_student_materials(db, user.school_id, user.id, lesson_id, locale if locale in ("en", "ar") else "en")

@router.put("/study-lessons/{lesson_id}/materials/{assignment_id}/completion")
async def completion(lesson_id: str, assignment_id: uuid.UUID, body: CompletionUpdate, user: Student, db: Db):
    try: return await svc.set_completion(db, user.school_id, user.id, lesson_id, assignment_id, body.completed)
    except svc.ResourceError as error: raise _http(error)

@router.get("/study-materials/{assignment_id}/download")
async def download(assignment_id: uuid.UUID, user: Current, db: Db):
    resource = await svc.get_download(db, user.school_id, user.id, user.role, assignment_id)
    if resource is None or not resource.storage_name: raise HTTPException(status_code=404, detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Material not found"}})
    path = (Path(settings.RESOURCE_STORAGE_DIR) / resource.storage_name).resolve()
    root = Path(settings.RESOURCE_STORAGE_DIR).resolve()
    if root not in path.parents or not path.is_file(): raise HTTPException(status_code=404, detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Material not found"}})
    return FileResponse(path, media_type=resource.media_type or "application/octet-stream", filename=resource.original_filename or resource.title)
