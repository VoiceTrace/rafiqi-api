"""Stable bilingual subject/chapter catalog and concept metadata.

Revision ID: f6b2c3d4e5f6
Revises: e5a1b2c3d4e5
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "f6b2c3d4e5f6"
down_revision = "e5a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    subjects = op.create_table("review_subjects", sa.Column("id", sa.String(100), primary_key=True), sa.Column("title", sa.JSON(), nullable=False))
    chapters = op.create_table("review_chapters", sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("subject_id", sa.String(100), sa.ForeignKey("review_subjects.id"), nullable=False), sa.Column("title", sa.JSON(), nullable=False))
    op.create_index("ix_review_chapters_subject_id", "review_chapters", ["subject_id"])
    op.add_column("review_lessons", sa.Column("chapter_id", sa.String(100), nullable=True))
    op.create_foreign_key("fk_review_lesson_chapter", "review_lessons", "review_chapters", ["chapter_id"], ["id"])
    op.create_index("ix_review_lessons_chapter_id", "review_lessons", ["chapter_id"])
    fixture = json.loads((Path(__file__).parent / "fixtures/review-catalog-v1.json").read_text(encoding="utf-8"))
    op.bulk_insert(subjects, fixture["subjects"])
    op.bulk_insert(chapters, fixture["chapters"])
    db = op.get_bind()
    lessons = sa.table("review_lessons", sa.column("id", sa.String), sa.column("chapter_id", sa.String), sa.column("content", sa.JSON))
    existing = {r.id: r.content for r in db.execute(sa.select(lessons.c.id, lessons.c.content))}
    catalog = {row["id"]: row for row in fixture["lessons"]}
    # Preserve any locally authored lessons, rather than deleting or relabeling them.
    for lid, content in existing.items():
        if lid in catalog:
            continue
        suffix = hashlib.sha256(lid.encode()).hexdigest()[:20]
        sid, cid = f"legacy-subject-{suffix}", f"legacy-chapter-{suffix}"
        titles = lambda field: {loc: content.get(loc, content.get("en", {})).get(field, lid) for loc in ("en", "ar")}
        db.execute(subjects.insert().values(id=sid, title=titles("subject")))
        db.execute(chapters.insert().values(id=cid, subject_id=sid, title=titles("chapter")))
        catalog[lid] = {"id": lid, "chapter_id": cid, "content": {**content, "subject_id": sid, "chapter_id": cid}}

    def enrich(content, template):
        result = deepcopy(content)
        result.update(subject_id=template["subject_id"], chapter_id=template["chapter_id"])
        for loc in ("en", "ar"):
            if loc not in result:
                continue  # Do not invent a translation for old custom content.
            result[loc].setdefault("concept_refs", template.get(loc, {}).get("concept_refs", []))
            refs = {q["id"]: q.get("concept_ref") for q in template.get(loc, {}).get("questions", [])}
            for q in result[loc].get("questions", []):
                if refs.get(q["id"]):
                    q.setdefault("concept_ref", refs[q["id"]])
        return result

    for lid, row in catalog.items():
        if lid in existing:
            row["content"] = enrich(existing[lid], row["content"])
            db.execute(lessons.update().where(lessons.c.id == lid).values(chapter_id=row["chapter_id"], content=row["content"]))
        else:
            db.execute(lessons.insert().values(**row))
    op.alter_column("review_lessons", "chapter_id", nullable=False)
    # Add metadata only: retain historical wording, rubrics, answers and completion.
    sessions = sa.table("review_sessions", sa.column("id", sa.Uuid), sa.column("lesson_id", sa.String), sa.column("content", sa.JSON), sa.column("state", sa.JSON))
    for session in db.execute(sa.select(sessions)).mappings().all():
        content = enrich(session["content"], catalog[session["lesson_id"]]["content"])
        state = deepcopy(session["state"])
        refs = {q["id"]: q.get("concept_ref") for loc in ("en", "ar") for q in content.get(loc, {}).get("questions", [])}
        for event in state["events"]:
            if event["kind"] in ("answer", "feedback") and refs.get(event.get("question_id")):
                event.setdefault("concept_ref", refs[event["question_id"]])
        db.execute(sessions.update().where(sessions.c.id == session["id"]).values(content=content, state=state))


def downgrade():
    # Keep seeded lessons and additive snapshot metadata to avoid losing student work.
    op.drop_index("ix_review_lessons_chapter_id", table_name="review_lessons")
    op.drop_constraint("fk_review_lesson_chapter", "review_lessons", type_="foreignkey")
    op.drop_column("review_lessons", "chapter_id")
    op.drop_index("ix_review_chapters_subject_id", table_name="review_chapters")
    op.drop_table("review_chapters")
    op.drop_table("review_subjects")
