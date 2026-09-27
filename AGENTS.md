# Rafiqi API agent instructions

Read `.claude/STATUS.md`, `.claude/CLAUDE.md`, and `docs/artifact.md` before work.
The Claude instructions and skills also apply to other coding agents.

- Follow `.claude/skills/fastapi-conventions/SKILL.md` for routes, schemas,
  and services: async routes, explicit response models, thin handlers,
  role dependencies, structured errors, and school-scoped queries.
- Follow `.claude/skills/db-migrations/SKILL.md` for model changes. Review
  generated Alembic migrations, preserve applied migrations, and verify
  upgrade and model/schema drift against PostgreSQL.
- Follow `.claude/skills/testing/SKILL.md` before completion. Cover the
  real happy path, rejected roles, and tenant isolation; run the full suite.
- Follow `.claude/skills/commit-conventions/SKILL.md`: small logical commits
  with `<TICKET-ID> <type>(<scope>): <description>` subjects.
- Preserve existing user changes and never commit secrets, database data,
  virtual environments, or runtime logs.
- Use README setup instructions. Verify the configured database is local
  before migrations, seeding, or integration tests. Tests must own and clean
  up their fixtures rather than altering existing school data.
- Report tested behavior separately from scaffolded or deferred functionality.
