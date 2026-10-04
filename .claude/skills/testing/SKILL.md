---
name: testing
description: Use whenever finishing a ticket, to validate the work before marking it done. Covers how tests are structured and run in rafiqi-api.
---

# Testing conventions

## Stack
- pytest + pytest-asyncio (routes are async, tests must be too)
- Use `httpx.AsyncClient` against the FastAPI app for route-level tests,
  not the sync `TestClient` — the app is async end to end, sync testing
  hides real bugs (e.g. missed `await`s).

## Structure
```
tests/
  conftest.py       # shared fixtures: test db session, test client, auth helpers
  test_<resource>.py  # mirrors app/api/routes/<resource>.py
```

## What every ticket needs, minimum
- At least one test that exercises the happy path of the new
  route/behavior end to end (not just a unit test of an isolated function).
- If the ticket touches auth/roles (most will), a test confirming the
  wrong role is rejected — not just that the right role succeeds.
- If the ticket touches multi-tenant data, a test confirming a user from
  School A cannot see School B's data. This is the single most important
  test category given PDPL — do not skip it to move faster.

## Running
`pytest` from the project root runs the full suite. Run it before marking
any ticket done — don't rely on "the new test I wrote passes," confirm
nothing else broke.

Check the **collected** count, not just the pass count. If one test file
fails to import, pytest aborts collection and the summary can still read
mostly-passing while whole files never ran. This has happened here and hid
nine tests along with the broken feature they covered.

Integration tests skip silently without `TEST_DATABASE_URL`. A skip is not
a pass — if the summary says `N skipped`, find out what, because those are
usually the tests that would have caught the bug:

```bash
TEST_DATABASE_URL="postgresql+asyncpg://rafiqi:rafiqi@127.0.0.1:5433/rafiqi_test" pytest -q
```

## A test that has never seen the bug proves nothing
After writing a regression test, revert the fix and confirm the test fails,
then restore. A test written after a fix has never been shown to detect
anything — this step is what makes it a regression test rather than
decoration.

## Definition of done, testing-wise
A ticket isn't done until: happy-path test passes, role-rejection test
passes (if applicable), tenant-isolation test passes (if applicable), and
the full suite is green — not just the new tests.

Then run the `qa` skill. Green tests mean the code does what the tests say;
QA is what proves the feature works in a real browser against a real stack,
which is a different claim and has repeatedly caught what tests missed.
