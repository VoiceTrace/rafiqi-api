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

## Definition of done, testing-wise
A ticket isn't done until: happy-path test passes, role-rejection test
passes (if applicable), tenant-isolation test passes (if applicable), and
the full suite is green — not just the new tests.
