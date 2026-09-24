"""Global demo catalog: no user or school data belongs in these tables."""
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.review import ReviewSubject, ReviewChapter, ReviewLesson
from app.schemas.review import SubjectOut, ChapterOut, Locale
from app.services.review import ReviewError
from app.services.review_assessment import validate_question_assessment


def catalog_seed():
    data = json.loads((Path(__file__).parents[1] / "data/review-catalog.json").read_text(encoding="utf-8"))
    subjects = {s["id"] for s in data["subjects"]}
    chapters = {c["id"]: c for c in data["chapters"]}
    for item in [*data["subjects"], *data["chapters"]]:
        if not (all(item["title"].get(loc) for loc in ("en", "ar"))):
            raise ValueError("Invalid bilingual catalog seed")
    for c in chapters.values():
        if not (c["subject_id"] in subjects):
            raise ValueError("Invalid bilingual catalog seed")
    for lesson in data["lessons"]:
        content = lesson["content"]
        if not (content["chapter_id"] == lesson["chapter_id"]):
            raise ValueError("Invalid bilingual catalog seed")
        if not (chapters[lesson["chapter_id"]]["subject_id"] == content["subject_id"]):
            raise ValueError("Invalid bilingual catalog seed")
        for loc in ("en", "ar"):
            localized = content[loc]
            if not (localized["objective"] and localized["key_points"] and localized["questions"]):
                raise ValueError("Invalid bilingual catalog seed")
            refs = {ref["id"] for ref in localized["concept_refs"]}
            if not (all(ref["title"] and ref["description"] for ref in localized["concept_refs"])):
                raise ValueError("Invalid bilingual catalog seed")
            if not (all(q["concept_ref"] in refs for q in localized["questions"])):
                raise ValueError("Invalid bilingual catalog seed")
            for question in localized["questions"]:
                validate_question_assessment(content["subject_id"], question)
        if not ([q["id"] for q in content["en"]["questions"]] == [q["id"] for q in content["ar"]["questions"]]):
            raise ValueError("Invalid bilingual catalog seed")
        if not ([r["id"] for r in content["en"]["concept_refs"]] == [r["id"] for r in content["ar"]["concept_refs"]]):
            raise ValueError("Invalid bilingual catalog seed")
    return data


async def seed_catalog(db: AsyncSession) -> None:
    """Idempotent insert-only seed: never overwrite edited content or session snapshots."""
    data = catalog_seed()
    for model, key in [(ReviewSubject, "subjects"), (ReviewChapter, "chapters"), (ReviewLesson, "lessons")]:
        for row in data[key]:
            await db.execute(insert(model).values(**row).on_conflict_do_nothing(index_elements=["id"]))
    await db.commit()


async def list_subjects(db: AsyncSession, locale: Locale) -> list[SubjectOut]:
    rows = (await db.execute(select(ReviewSubject).order_by(ReviewSubject.id))).scalars()
    return [SubjectOut(id=row.id, title=localized_title(row.title, locale)) for row in rows]


def localized_title(title: dict, locale: Locale) -> str:
    if not title.get(locale):
        raise ReviewError("catalog_translation_unavailable", 409)
    return title[locale]


async def list_chapters(db: AsyncSession, subject_id: str, locale: Locale) -> list[ChapterOut]:
    if await db.get(ReviewSubject, subject_id) is None:
        raise ReviewError("subject_not_found", 404)
    rows = (await db.execute(select(ReviewChapter).where(ReviewChapter.subject_id == subject_id).order_by(ReviewChapter.id))).scalars()
    return [ChapterOut(id=row.id, subject_id=row.subject_id, title=localized_title(row.title, locale)) for row in rows]
