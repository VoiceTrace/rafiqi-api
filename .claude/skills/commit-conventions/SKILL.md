---
name: git-commits
description: Use whenever staging or committing changes in rafiqi-api or rafiqi-frontend. Covers commit size, message format, and when to split work into multiple commits.
---

# Git commit conventions

## Format
```
<TICKET-ID> <type>[optional scope]: <description>
```
Examples:
- `A1 feat(models): add student profile table and migration`
- `A1 fix(profile): correct nullable constraint on confidence field`
- `B2 feat(lesson-prep): generate objectives via LLM gateway`
- `C2 chore(realtime): add websocket connection health check`
- `A3 test(profile): add tenant-isolation test for profile updates`

## Types (pick one, lowercase)
- `feat` — new capability the ticket asked for
- `fix` — bug fix, including fixing your own earlier commit in this ticket
- `refactor` — no behavior change, code structure only
- `test` — adding/adjusting tests with no production code change
- `chore` — tooling, config, deps, migrations infra (not the migration's own feat commit)
- `docs` — CLAUDE.md, STATUS.md, README, skill files

## Scope
Optional, in parentheses, lowercase — name the module/area touched
(`models`, `profile`, `realtime`, `lesson-prep`). Skip it if the change is
genuinely project-wide (e.g. a `chore` touching config).

## Ticket ID
Always first, no punctuation after it, matches the ticket ID from the
engineering plan (A1, B5, C2, etc.). If a commit doesn't map to a specific
ticket (e.g. fixing something STATUS.md flagged, or a cross-cutting fix),
use the ticket ID it's closest to and say why in the body if it's not
obvious.

## Keep commits small — this is the part that matters most
One commit = one logical change, not one ticket = one commit. A ticket
that touches a model, a migration, a route, and a test is normally at
least 2-4 separate commits, not one. Concretely:
- The data model + its migration is its own commit.
- The route/service logic is its own commit.
- Tests are their own commit if written after the fact, or bundled with
  the change they test if written alongside it — either is fine, just
  don't bundle unrelated changes together.
- If you catch yourself about to write a commit message with "and" doing
  a lot of work ("add model and route and tests and fix typo"), stop and
  split it before committing, not after.

## Commit body (when to add one)
Skip the body for small, self-explanatory commits — the subject line is
enough. Add a short body (2-4 lines, blank line after the subject) when:
- The "why" isn't obvious from the diff (e.g. a non-obvious design choice)
- You made a decision CLAUDE.md/STATUS.md doesn't already cover and want
  it traceable later
Don't restate what the diff already shows.

## Never
- Don't commit a ticket as one giant commit at the end "to save time" —
  it defeats the point of being able to trace history and revert cleanly.
- Don't mix two ticket IDs in one commit. If a fix for ticket A surfaces
  while working on ticket B, commit it separately under A's ID.