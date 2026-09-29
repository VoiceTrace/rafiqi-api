# What must never happen

Read before Phase 3. Happy-path checks confirm a feature works. These confirm it
cannot be abused, and in this product they are the checks that matter most: the users
are minors, the data is theirs, and PDPL applies.

Work through every section that the ticket touches. Each one has a concrete "attempt
this, expect that".

## 1. Role gates

Two roles exist: `teacher` and `student`, enforced by `require_teacher` /
`require_student` in `app/api/deps.py`.

| Attempt | Expect |
|---|---|
| Student token on a teacher route | `403` |
| Teacher token on a student route | `403` |
| No `Authorization` header | `401` |
| Malformed or expired token | `401` |

Test the rejection, not just the success. A route with no dependency declared passes
every happy-path test and is wide open.

## 2. Tenant isolation (PDPL — the highest-stakes category)

Every query touching user data must be scoped to `school_id`. This is the rule that
protects one school's children from another school's staff.

| Attempt | Expect |
|---|---|
| Teacher from School B reads School A's assignment | `404` |
| Student from School B reads School A's homework | `404` |
| School B lists their own homework, A has published | `[]` — nothing from A |
| Student acts on another student's record, same school | `403` or `404` |

**`404`, not `403`, across tenants.** `403` confirms the record exists, which is
itself a leak. Within a school, `403` on someone else's record is fine.

Test at the **list** endpoint as well as the detail endpoint. Detail routes usually
get the scoping; list routes are where a missing `WHERE` quietly returns everything.

## 3. Disclosure — what reaches whom, and when

This product has a specific hazard: several fields are legitimate for one audience and
forbidden for another. The teacher payload and the student payload are different
contracts over the same rows.

Must never reach a student:

| Field | Rule |
|---|---|
| `correct_answer` / answer key | Never, at any point, on any student route |
| Hints not yet revealed | Only hints the student spent a reveal on come back |
| `internal_answer_key`, private rubrics, keyword lists | Never |
| A grade before the teacher approves | See below |
| Another student's answers, scores, or hint usage | Never |

Assert on the **raw response text**, not a parsed field — a leak often rides along in
a nested object a typed check would skip:

```python
assert "correct_answer" not in response.text
assert "hints" not in response.json()["questions"][0]
```

### The status-transition trap

A field can be correctly gated on one route and leak on another. This is the bug that
motivated this section:

`grade_submission` writes `score` as soon as a teacher enters marks, including when
`approve=false` (status becomes `graded`, not `approved`). The results endpoint gated
correctly on `approved`. The **list** and **detail** endpoints returned `score`
unconditionally — so a student polling their homework list saw the mark before the
teacher released it.

So: when a rule says "not until X", enumerate **every** state before X and **every**
route that returns the field.

```
assigned → in_progress → submitted → graded → approved
                                     ^^^^^^   the dangerous one
```

Check `graded` explicitly. It is the state where the data exists but must stay hidden,
and it is the one nobody thinks to test.

## 4. Immutability after a transition

Once work is handed in, it is evidence. Verify the door is actually shut:

| Attempt | Expect |
|---|---|
| Submit an already-submitted assignment | `409` |
| Reveal a hint after submitting | `409` |
| Edit an assignment after distribution | `409` |
| Distribute an already-distributed assignment | `409` |

Also confirm nothing was written on the rejected call — a guard that raises *after*
`db.add()` still mutates. In unit tests: `db.add.assert_not_called()` and
`db.commit.assert_not_awaited()`.

## 5. Boundaries and limits

Where a maximum exists, test at and beyond it, and in both layers.

- The API rejects the over-limit action (a 4th hint reveal → `409`).
- The UI does not offer it (no reveal button once the cap is reached).
- Below the maximum still works — a question authored with **one** hint must allow
  exactly one reveal and then stop. "Up to 3" is a ceiling, not a quota, and
  hardcoding `3` where the content has fewer produces a button that always errors.

## 6. Replay and concurrency

For anything carrying a `request_id` or a version:

| Attempt | Expect |
|---|---|
| Replay an accepted `request_id` | Saved state returned, **not** applied twice |
| Send a stale `expected_version` | `409` |
| Two concurrent creates of a unique resource | Both succeed, same row, no duplicate |
| Two concurrent writes to one row | One `200`, one `409` |

Concurrency is testable without ceremony:

```python
results = await asyncio.gather(*[client.post(url, json=payload) for _ in range(3)])
assert len({r.json()["id"] for r in results}) == 1
```

## 7. Input validation

Confirm rejection happens **before** any write:

- Answers that do not cover exactly the assignment's questions
- An option id that belongs to a different question
- Duplicate ids where uniqueness is required
- Empty or whitespace-only text where content is required
- Values past `max_length`
- Naive datetimes where the schema requires an offset

## 8. Rafiqi AI boundary

If the ticket touches the AI layer, two rules hold regardless of feature:

- The AI layer must never receive `student_id` or `school_id`.
- Anything labelled a deterministic mock must not acquire a real model dependency.

## Turning this into permanent coverage

When QA finds one of these, add the test next to the criterion it protects rather than
in a general file. Name the test after the rule so a future failure explains itself:

```python
def test_score_is_hidden_until_the_teacher_approves(): ...
def test_students_from_another_school_cannot_read_it(): ...
```

Then verify it fails against the unfixed code (Phase 5). An adversarial test that
never saw the attack it describes is decoration.
