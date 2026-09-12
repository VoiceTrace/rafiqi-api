---
name: db-migrations
description: Use whenever a ticket requires a new or changed database table/column (e.g. A1 profile data model, B1 lesson prep data model). Covers the Alembic workflow for this project.
---

# Database migrations (Alembic)

## Workflow
1. Change the SQLAlchemy model(s) in `app/models/`.
2. Generate a migration: `alembic revision --autogenerate -m "<ticket-id>: <short description>"`
   e.g. `alembic revision --autogenerate -m "A1: add student profile table"`
3. **Read the generated migration file before running it.** Autogenerate is
   not always right — check column types, nullability, and that it isn't
   dropping something it shouldn't.
4. Run it locally: `alembic upgrade head`
5. Never hand-edit a migration file that has already been applied anywhere
   outside your local machine. If a change is needed after that point,
   write a new migration instead.

## Naming
- Migration message always starts with the ticket ID, matching the commit
  convention in CLAUDE.md/STATUS.md — makes it trivial to trace a schema
  change back to the ticket that caused it.

## Multi-tenancy
- Any new table holding student, teacher, or school data needs a
  `school_id` foreign key from the start. Don't add it later as an
  afterthought — retrofitting tenant scoping onto an existing table is
  much more error-prone than including it at creation.

## Before marking a ticket done
- Migration file has been read and matches intent, `alembic upgrade head`
  runs clean, and any new student/teacher-facing table has school-scoping
  in place.
