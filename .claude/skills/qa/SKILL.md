---
name: qa
description: Run real end-to-end QA on a ticket before calling it done — boot the API and the frontend against a real database, drive every acceptance criterion through a browser, and prove the tests would actually catch a regression. Use this whenever you finish implementing a ticket, fix a bug, review someone else's work (Codex, a teammate) against a spec, or are asked to "QA", "verify", "test the flow", "check it works", or "make sure this is done" in rafiqi-api or rafiki-frontend. Also use it before opening a PR. Running pytest and reporting green is NOT QA — this skill exists because a passing suite has repeatedly hidden broken features in this project.
---

# QA — verifying a ticket for real

`testing` covers writing tests. This skill covers proving the feature works: a real
API, a real frontend, a real database, a real browser, and evidence for every
acceptance criterion the ticket claims to satisfy.

## Why this skill is strict

Three things have actually happened in this codebase. Each one produced a confident
"it works" that was false:

- **A green suite that ran almost nothing.** One test file imported a helper another
  file had deleted. Pytest aborted collection, reported `1 failed, 92 passed`, and
  nine tests never loaded at all. The feature they guarded was broken.
- **QA against a stale server.** A dev server left running on port 8000 served
  pre-fix code. The browser check failed, and the failure looked like a bug in code
  that was actually correct.
- **A test that passed against broken code.** Assertions written after the fix, never
  checked against the bug, so they asserted nothing.

The phases below are ordered to catch those three classes first, because each one
invalidates everything after it.

## Phase 0 — Know exactly what you are verifying

You cannot QA "the ticket". You QA a list of specific claims.

Write the list down before touching anything. Sources, in priority order:

1. Acceptance criteria the user pasted into the conversation — these win over
   everything, including docs in the repo.
2. `docs/` — `artifact.md` (the MVP plan, epics and their acceptance criteria),
   plus any feature-specific doc such as `docs/review-companion.md`.
3. `rafiki-frontend/design/boards/*.md` — the approved UI for each screen.

**Check for a dated correction before reporting a conflict.** Boards in this repo are
amended in place, with lines like "2026-09-29 approved correction: ... supersedes the
wording below". Read the whole board, not the first matching paragraph — the apparent
contradiction is often already resolved further down, and chasing a settled one wastes
a chunk of the pass.

**When a real disagreement survives that check, stop and ask.** Boards have genuinely
contradicted pasted requirements here, and the answer changes what you verify. Report
it with both quotes and their dates, and let the user decide rather than guessing.

For each criterion, write the concrete observation that would prove it. "Hints work"
is not checkable. "A 4th reveal returns 409 and the UI shows no reveal button" is.

## Phase 1 — Get a real stack up

This is where most QA time is lost, and where false results come from. Full detail
in `references/environment.md` — read it before starting, it covers the port and
identity traps specific to this machine.

The short version, in order:

1. **Database.** Confirm which postgres you are actually talking to. Another postgres
   has repeatedly occupied 5432 on this machine, and it fails with `password
   authentication failed`, which reads like a credentials problem and is not one.
2. **Migrate.** `alembic upgrade head` against a dedicated `*_test` database.
3. **Seed.** `scripts/seed.py`. Then check the seed actually satisfies the feature's
   preconditions — grade-scoped homework silently reaches nobody if seeded students
   have no `grade_level`.
4. **API.** Start it, then **confirm it bound** and **confirm it is running your code**.
5. **Frontend.** Start it pointed at that API.

Three rules that have each cost a full debugging detour:

- **Never assume a process you did not start is running your code.** If something is
  already on the port, find out what it is. Do not kill it — it may be a teammate's or
  another agent's. Use a different port and point the frontend there.
- **Pick your ports and container names per session, and carry them as variables.**
  The obvious choices (5432, 5433, 8000, 3000) are routinely taken here, sometimes by
  a previous QA pass. Hardcoding one is how you end up attached to someone else's
  stack.
- **Prove the server is your build** by requesting a field or route you just added. If
  it is missing, you are talking to a stale process, and every result after that is
  noise.

## Phase 2 — Static gates

Cheap, and they invalidate everything downstream if they fail.

**Run the suite before you rely on the seeded data.** Some fixtures recreate tables in
the database `TEST_DATABASE_URL` points at, so running the suite after seeding can
leave you with an empty database and a confusing Phase 3. Either run the suite first
and re-seed afterwards, or give the suite its own database separate from the one the
API is serving. The fixtures refuse any database whose name does not end in `_test`,
which is the guard that stops this from ever touching real data.

```bash
# From rafiqi-api/. The suite must COLLECT, not just pass — check the collected count.
.venv/Scripts/python.exe -m pytest -q

# Integration tests skip silently without this — a skip is not a pass.
TEST_DATABASE_URL="postgresql+asyncpg://rafiqi:rafiqi@127.0.0.1:$QA_PORT/rafiqi_test" \
  .venv/Scripts/python.exe -m pytest -q
```

If the summary says `N passed, M skipped`, find out what skipped and why. Skipped
integration tests are the ones that would have caught the bug.

Frontend, from `rafiki-frontend/`:

```bash
npx tsc --noEmit     # must exit 0
npm run lint         # warnings are usually fine; errors are not
```

Note the pre-existing warning count before your change so you can tell what you added.

## Phase 3 — Verify each criterion at the API

Before the browser, prove the contract holds at the API. It is faster to debug, and
it tells you whether a later browser failure is backend or frontend.

Drive real HTTP against the running server with a real token. For each criterion,
assert the specific observation you wrote in Phase 0.

The highest-value checks in this product are about **what must never reach whom** —
answer keys, grades before a teacher approves, unrevealed hints, another school's
data. `references/adversarial.md` has the full matrix. Do not skip it: these are the
failures that matter most and the ones a happy-path test never finds.

## Phase 4 — Drive it in a browser

A passing API contract does not mean the feature works. A form input marked `required`
can make a valid submission impossible; local state can drop data the API returned
correctly. Both have happened here.

`references/browser.md` has the Playwright setup for this app — login, module
resolution, selectors, and the traps that produce false failures.

Cover, for every criterion that has a UI:

- The **happy path**, as a user performs it.
- **After a reload**, for anything the user spent something on or that must persist.
  State held only in React is lost on refresh; this is a real defect class here.
- The **blocked path** — the UI must not offer an action the API rejects. A button
  that always 409s is a bug even though the API is correct.
- **Arabic** (`/ar/...`) for any layout change, since the app is RTL-mirrored.

Screenshot each checkpoint. A screenshot is the difference between "I believe it
works" and evidence.

## Phase 5 — Prove the tests are not vacuous

A test written after a fix has never seen the bug. Confirm it would catch one by
**breaking the behaviour on purpose** and checking the test notices.

Pick the method that fits your situation:

**You have an uncommitted diff** (you just wrote the fix): revert it, run the test,
restore.

```bash
git stash push -- <file>     # or edit the line back by hand
pytest tests/<test> -q       # must FAIL, naming the real problem
git stash pop                # restore, re-run, green
git status --short           # confirm the tree is as you found it
```

**The fix is already committed, or you were told not to modify files** (verifying
someone else's branch): do not edit the repo. Break the behaviour in memory for one
run with `monkeypatch`, which touches nothing on disk:

```python
def test_the_guard_is_load_bearing(monkeypatch):
    from app.services import homework as svc
    monkeypatch.setattr(svc, "_student_visible_score", lambda sa: sa.score)  # reintroduce the leak
    # now assert the protective test's condition fails
```

Put that file in `tests/` so imports resolve the way the suite expects. There is no
`tests/conftest.py`, so if you run it from elsewhere set `PYTHONPATH` to the repo root.

Either way the question is the same: *if this protection disappeared, would anything
tell me?*

**If breaking it changes nothing, find out which of two things is true** — the test is
vacuous and needs rewriting, or that code is genuinely unreachable because another
layer already prevents it. Both are worth reporting; they are not the same finding.
A schema that caps a list at three makes a service-level ceiling redundant, which is
fine as defence in depth but means no test actually guards that line.

Do this for at least the most important behaviour the ticket changed. It takes a
minute and is the only thing separating a regression test from a decorative one.

## Phase 6 — Clean up after yourself

Leave the machine as you found it, and say what you changed:

- Stop servers and containers **you** started, by PID or by the unique name you chose.
  Never stop something by port — see `references/environment.md`. Everything else
  stays running, including things that look abandoned.
- **Remove anything you wrote into either repo.** QA artifacts must never land in
  `rafiki-frontend/design/boards/` — that directory is approved design reference.
  `git status` should show only the changes the ticket intended.
- **Keep your scratchpad.** Screenshots and scripts there are your evidence for
  Phase 7 and cost nothing to leave; the scratchpad is session-scoped and outside
  both repos. Cite screenshots by path in the report rather than deleting them.
- Tell the user about anything you found but did not touch: a stale server, a port
  conflict, another agent's process. They need to know it is there.

## Phase 7 — Report

Lead with the verdict, then the evidence. Structure:

```markdown
## Verdict
Ready / Not ready — one sentence on why.

## Criteria
| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Only students in the grade can see it | PASS | peer + student see it, other school sees [] |
| 2 | 4th hint reveal blocked in UI and API | PASS | API 409; no reveal button (QA-S02.png) |

Cite the concrete observation — a status code, a count, a screenshot path. "Works"
is not evidence.

## Defects found
Each with: what happens, the trigger, which criterion it breaks, and severity.

## Not verified
What you could not check and why — an unreachable dependency, a criterion with no
UI yet, something that needs the user's decision.

## Environment notes
Anything about the machine the user should know.
```

Be specific about what you did **not** verify. An honest gap is useful; a silent one
destroys trust in the whole report.

## When QA finds a defect

Fix it if it is in the ticket's scope, then re-run the phases it touches — not the
whole pass, just the affected ones. If it is out of scope, report it with enough
detail to act on (file, line, trigger, impact) and keep going. Do not silently
expand the ticket.

## Reference files

- `references/environment.md` — booting a real stack; the port, identity, and seed
  traps that cause false results. Read before Phase 1.
- `references/browser.md` — Playwright against this app: login, selectors, reload
  checks, RTL. Read before Phase 4.
- `references/adversarial.md` — the role, tenant, and disclosure matrix. Read before
  Phase 3; these are the checks that matter most in this product.
