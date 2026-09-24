# Rafiqi — MVP Engineering Plan Review (Revision 2)

**Reviewer:** Younis  
**Date:** 12 September 2026  
**Covers:** Epics A, B, C (deferred) + proposed Epics D, E

---

## Reading this revision

| Label | Meaning |
|-------|---------|
| **New** | Added in this revision — not in the original plan or the first review pass |
| **Revised** | Existed before; its status or priority has changed as a result of the scope proposal |
| **Deferred** | Proposed for v2. Kept in the document so the reasoning stays on record |
| *(plain)* | First review pass, carried over as-is |

---

## What changed since revision 1

Three decisions, taken together:

1. **Epic C (during-class) is proposed for deferral to v2.** It rests on an unvalidated assumption that every student has an open device during class, and it carries the most expensive infrastructure in the plan in service of the least validated behaviour.
2. **Two epics replace it: D (study sessions with Rafiqi) and E (homework generation).** Eleven tickets in place of eight — but without the realtime infrastructure, and with a far stronger learning signal.
3. **A concept-level mastery model becomes a blocker, not a nice-to-have.** Targeted homework cannot be generated from personality traits; it needs to know what the student got wrong and why.

**Net effect on the product spine:** Study → Profile → Prep + Homework → Study. A closed loop with no dependency on what happens inside the classroom.

---

## How to read this review

The architecture and ticket breakdown are solid. Entities are well chosen, dependencies are correctly identified, and flagging consent and compliance early (A8) is the right instinct.

This review does not challenge the technical design. It addresses three things the plan leaves open:

1. **Product decisions currently left to implementation.** Several tickets will be built correctly from an engineering standpoint and wrongly from a pedagogical one, because no acceptance criteria define the intended behaviour.
2. **Connective tissue between epics.** Each epic works standalone. The links that make them one product are either missing or scheduled last.
3. **One unvalidated assumption carrying the most expensive infrastructure in the plan.**

**Priority labels:** `Blocker` must resolve before that ticket is built · `High` · `Medium` · `Low`

---

## §0 — Cross-cutting issues

| # | Issue | Impact |
|---|-------|--------|
| X1 | `StudentProfile` never feeds `LessonPrep`. No ticket in Epic B reads profile data. The teacher plans a lesson while Rafiqi holds a full profile of every student in the room, and says nothing. | Epic A becomes a viewing feature rather than something that changes instruction. This is the largest gap in the original plan. See ticket N1. |
| X2 *(Revised)* | The class → profile handoff (C8) sits in "polish". Until it ships, nothing that happens in class reaches the profile. | Superseded by the scope proposal. With Epic C deferred, the handoff into A3 now comes from the study session instead — ticket D6. |
| X3 *(Revised)* | No entity represents understanding or mastery. The model captures how a student learns, never what they have understood. | Escalated from "positioning decision" to **Blocker**. Epic E cannot generate targeted homework without it. See ticket D4. |
| X4 *(Revised)* | Epic C assumes every student has an open device during class. Nowhere stated or validated. | Resolved by the scope proposal: deferring Epic C removes the dependency entirely. Study and homework both happen outside class hours, where device access is not in question. |
| X5 | No acceptance criteria on tickets that encode product decisions. Roughly six tickets contain a judgement call that engineering will otherwise resolve by default. | Rework. See ticket N3. |
| X6 *(New)* | Homework policy is unvalidated. Some international schools minimise or restrict homework in certain year groups. | Same class of assumption as X4 — do not repeat the mistake. Validate with the same schools, in the same conversation, before Epic E is built. |

---

## §1 — Epic A — Student Profile System

| Ticket | Comment | Requested change | Priority |
|--------|---------|-----------------|----------|
| A1 | Schema shape depends on answers that live in A8 — retention period, deletion rights, ownership on student transfer, and whether the profile may ever inform formal assessment. Building A1 first means reworking it later. | Resolve A8 before A1 is finalised. | **Blocker** |
| A1 | The profile accumulates over months. Confirm the schema supports amendment with history, not overwrite — we need to distinguish "the student changed" from "the earlier read was wrong". | Add explicit versioning to the schema. | High |
| A1 *(Revised)* | With Epic D in scope, the profile now has two halves: who the student is (traits, narrative reads) and what they understand (concept-level mastery). The schema must accommodate both, related but separately queryable. | Extend A1 to reference `MasteryRecord` (D4). | **Blocker** |
| A2 | The Rafiqi persona prompt is a product artefact, not a configuration string. Early response data shows resistance to a purely Socratic style — this needs iteration and testing, not a one-pass write. | Treat the persona prompt as its own deliverable with review cycles. | High |
| A2 *(Revised)* | A2 is scoped as "chat thread persistence + persona". Epic D is the structured study loop that runs on top of this. A2 is the plumbing; it is not the Cave. | Re-estimate A2 with Epic D's scope visible, so the Cave is not under-budgeted twice. | High |
| A3 | The promotion rule from *forming* to *confident* is undefined. Number of observations? Consistency across subjects? Elapsed time? This is a product rule and should not be chosen at implementation time. | Define and document the promotion rule before A3 is built. | **Blocker** |
| A3 | Output stability is untested. The same transcript should yield materially the same profile updates on repeated runs. | Add to definition of done: run the same transcript three times and diff the outputs. | High |
| A3 | Confirm updates are diff-based against the existing profile, not full regeneration. | Make explicit in the ticket. | High |
| A5 | Scheduled in phase 5, after A6 ships. Real students would see Rafiqi's read of them with no way to object. | Move A5 to ship **alongside** A6. Not after. | **Blocker** |
| A6 | No definition of what the student actually sees. Numeric trait scores shown to a child are harmful; an actionable narrative read is useful. Same data, opposite outcomes. | Acceptance criteria required. Proposed rule: narrative reads and teaching-relevant statements only — no numeric trait scores, no comparative framing. | **Blocker** |
| A7 | A roster of thirty cards with no ordering will be opened once and never again. The teacher needs "these three need you now, and here is why". | Add a default attention-priority ordering to the ticket. | High |
| A8 | Correctly flagged, wrongly sequenced. These answers determine A1's schema and A3's output format. | Move A8 to phase 1. | **Blocker** |
| A8 | Questions to answer explicitly: who consents (guardian, school, or both); retention period and post-retention handling; guardian deletion rights; what happens to the profile when a student leaves the school; and an explicit written statement that the profile is never used for formal assessment. | Produce a written data-handling note, not just a review. | **Blocker** |
| A8 *(Revised)* | Epic D adds performance data — attempts, errors, mastery per concept — which is a more sensitive category than behavioural reads, and Epic E sends output to the home. Both widen the compliance surface. | Extend A8's scope to cover performance data and parent-visible output before D4 and E3 are built. | **Blocker** |
| A9 | Marked optional. The teacher sees the student five times a week. If Rafiqi states something the teacher knows is wrong and the teacher cannot correct it, we lose the teacher — and the teacher decides whether the product stays in the school. | Promote A9 to MVP. It is the teacher-side mirror of A5. | High |

---

## §2 — Epic B — Pre-Class Flow

| Ticket | Comment | Requested change | Priority |
|--------|---------|-----------------|----------|
| B3 | Correct as written. Together with A5 it establishes the product principle: Rafiqi proposes, the human decides. Keep this consistent everywhere — including E4. | No change. | — |
| B5 | The epic's payoff (B6) depends on students actually completing the warm-up. The plan contains no mechanism for that: no reminder, no incentive, no definition of completion. | See ticket N4. B5 is not complete without it. | **Blocker** |
| B6 | Highest-value ticket in the epic and arguably in the original plan. This is the moment a teacher sees something they have never had before. | Sequence it earlier — it is the strongest demonstration asset in Epic B. | High |
| B6 | No minimum-coverage rule. A card built from eight of thirty responses must not be presented as a class-level finding. | Define a coverage threshold; below it the card states low coverage explicitly. | High |
| B7 | Unclear where captured questions surface. As a separate list, the teacher will not open it. | Merge into the B6 card — one pre-class briefing surface, not two. | Medium |
| B8 | Correctly deprioritised for engineering. Note for planning: this is the first thing teachers ask for in demos, because it is the only ticket that visibly saves them time rather than making them better informed. | Keep priority, but do not stub it for school-facing demos. | Medium |
| — | Nothing in this epic reads student profile data (X1). | See ticket N1. | **Blocker** |
| — *(Revised)* | The missing post-lesson feedback loop is now partly answered: Epic E's results feed back into mastery (E5), which informs the next prep cycle. Content-level efficacy (did these check-questions work?) remains open. | Keep N5 as v2 scope. | Low (v2) |

---

## §3 — Epic C — During-Class Flow

> **Proposed for v2 — defer this epic in full**

The comments below stood in revision 1 and are kept on record. The recommendation has changed from "fix these before building" to "do not build this in v1".

**Reasoning:**

- It targets the **worst available attention window.** Mid-lesson, the teacher has effectively zero spare attention and the student's is committed to the lesson. Study time has both in abundance.
- **The signal is weak for the price.** C3 yields "typing / not typing". A study session yields what was attempted, where it failed, how many tries, whether a hint was taken, and at which step the student stopped.
- **C2 is the single most expensive item in the plan** — persistent connections, reconnection, replay-on-rejoin — and it serves the least validated behaviour, on an unstated device assumption (X4).
- It **requires the school to change how a lesson runs** — the hardest sell in education. Study and homework already exist; we improve them where they are.

What we give up is the live demo moment. The replacement: thirty differentiated homework sets generated in one second, each with a line explaining why this student received that. That demonstrates something impossible by hand, rather than something done faster.

| Ticket | Comment (retained from revision 1) | Status |
|--------|------------------------------------|--------|
| C2 | Most expensive infrastructure in the plan, supporting the least validated behaviour, on an unstated device assumption. | Deferred to v2 |
| C3 | Input is keyboard activity; output is a colour verdict about a child, shown live to a teacher. A silent student may be listening closely; a fast typist may be transcribing without understanding. If this is ever built, display observed activity ("writing now", "no activity for 6 min"), not green/red judgements. | Deferred to v2 — constraint carries forward |
| C4 | Drill-down exposes who asked. If students believe questions are anonymous and discover otherwise, the trust built in B7 is lost. Decide attribution policy and state it visibly. | Deferred to v2 — constraint carries forward |
| C8 | The ticket that closes the loop into A3. | Replaced by D6 |
| C1, C5, C6, C7 | No objections in revision 1. | Deferred to v2 |

---

## §4 — Epic D — Study Sessions *(New)*

The student studies a lesson with Rafiqi outside class. This is where the richest learning signal in the product is generated, and it replaces Epic C as the source of behavioural and performance data.

**Ticket ceiling: six.** Anything beyond these six goes on the v2 list rather than into the epic.

| Ticket | Scope | Key acceptance criteria | Priority |
|--------|-------|------------------------|----------|
| D1 | `StudySession` entity — linked to a `Lesson`, owned by one student, with lifecycle states. | A session can be resumed after interruption without losing progress. Multiple sessions on the same lesson are distinguishable. | High |
| D2 | Study loop stages as an explicit state machine, not free chat. Rafiqi knows which stage the student is in and what ends it. | Stage transitions are recorded. The student can see where they are in the session. A stage cannot be skipped silently. | High |
| D3 | Attempt capture — every answer stored with correctness, the concept it targets, and a classified error type. | Error types come from a defined taxonomy per subject, not free text. An attempt is never stored without a concept reference. | **Blocker** |
| D4 | `MasteryRecord` — concept-level understanding per student. Not a grade: attempts, outcomes, and the dominant error pattern. | Answers "what does this student not understand, and in what way". Queryable per student and aggregated per `ClassGroup`. This is what Epic E consumes. | **Blocker** |
| D5 | Next-step selection and the hint ladder — what Rafiqi asks next, and how much help it gives before revealing. | Escalation is defined and bounded: a student cannot be left stuck, and cannot extract the answer on the first ask. Hint level taken is recorded as signal. | High |
| D6 | Session close — summary card for the student, and handoff of session data to profile extraction (A3) and to D4. | Replaces C8. Both handoffs are verifiable: a completed session measurably updates both the profile and the mastery record. | **Blocker** |

---

## §5 — Epic E — Homework *(New)*

The teacher issues homework built from what each student actually got wrong. This is work a teacher cannot do by hand for thirty students — not work we are doing faster.

**Ticket ceiling: five.** Human marking and open-response questions are explicitly out of scope — see §7.

| Ticket | Scope | Key acceptance criteria | Priority |
|--------|-------|------------------------|----------|
| E1 | `HomeworkAssignment` schema — per class, per student, linked to lesson and to targeted concepts. | Every generated item traces to the `MasteryRecord` entry that produced it. | High |
| E2 | Class gap digest — aggregate mastery across the class into "what this class got wrong", the post-lesson mirror of B6. | Same coverage rule as B6: below threshold, the digest states low coverage rather than presenting a class-level claim. | High |
| E3 | Differentiated generation — each student's set built from their own gaps, in self-checking formats only (single correct answer, multiple choice, spot-the-error in worked steps). | No item requires human judgement to mark. The student learns whether they were right without the teacher picking up a pen. Results post back automatically. | **Blocker** |
| E3 | Visible-differentiation rule. If one student's homework is plainly easier than another's, students and parents will notice and object. | Same item count and same presentation across the class. Variation lives in scaffolding and concept focus, never in a stated level. No student-visible difficulty label. | **Blocker** |
| E4 | Teacher review — every generated set is editable and requires explicit approval before it is sent. | Mirrors B3 and A9. Nothing reaches a student or a home without a teacher having approved it. | **Blocker** |
| E5 | Distribution, submission, and feedback into `MasteryRecord`. | Homework outcomes update mastery without manual entry, closing the loop back into D4 and the next study session. | High |

### Why self-checking formats are a constraint, not a preference

The moment we generate homework, the next question from the teacher is "and will you mark it?". If the answer is no and the format needs human marking, we have added work to the teacher's week rather than removing it — and the feature becomes a liability.

Restricting E3 to self-checking formats resolves this without adding a marking epic: the student gets immediate feedback, the teacher gets results without marking, and the outcome posts straight back into mastery. Open-response questions requiring human judgement are v2.

---

## §6 — Additional tickets

| # | Ticket | Rationale |
|---|--------|-----------|
| N1 | Class profile digest for lesson prep — surface aggregated `StudentProfile` signals for a `ClassGroup` inside the `LessonPrep` screen. | Closes X1. Turns Epic A from a viewing feature into something that changes instruction. |
| N2 *(Revised)* | Post-session profile handoff — promote C8 out of polish. | Superseded by D6. With Epic C deferred, the handoff originates from the study session. |
| N3 | Acceptance-criteria pass on product-decision tickets — A3, A6, A7, B6, and now D4, D5, E3. | Closes X5. Small effort; prevents rework on seven tickets. |
| N4 | Prime participation mechanics — reminder timing, definition of completion, behaviour at low participation. | B5 and therefore B6 are unusable without it. |
| N6 *(New)* | School validation call — one conversation with two or three target schools covering device access in class and homework policy by year group. | Closes X6 and confirms X4's resolution. Fifteen minutes of calls that determine weeks of engineering. |

---

## §7 — Revised sequencing

```
0. Decisions (no code)    A8 answers · A3 promotion rule · A6 disclosure rule
                          · D4 mastery model shape · N6 school validation

1. Foundations            A1 · A2 · B1

2. Profile loop + trust   A3 → A6 + A5 → A7 + A9

3. Study loop             D1 · D2 → D3 → D4 → D5 → D6

4. Pre-class loop         B2/B3 → B5 + N4 → B6/B7

5. The link               N1  (profile digest into prep)

6. Homework loop          E1 → E2 → E3 + E4 → E5

7. Polish                 B4 · B8 · N5

–  Live loop (v2)         C1 · C2 → C3 → C4 → C5 → C6 → C8
```

**Three things to note about this order:**
- The study loop (D) comes before the homework loop (E), because E consumes what D produces — there is no differentiated homework without mastery data.
- The link ticket N1 sits between them, so by the time homework generation is built, both profile and mastery are feeding the teacher's surfaces.
- Trust mechanisms (A5, A9, E4) ship **with** the features they protect, never after them.

---

## §8 — Parked for v2

*None of the below is open for discussion during v1.*

- The whole of Epic C — live engagement, live question clustering, highlight broadcast, in-class notes. With the C3 and C4 constraints carried forward if it is ever revived.
- Human marking and open-response homework questions.
- Group or peer study sessions.
- Lesson efficacy feedback (N5) — recording whether generated objectives, flow and check-questions actually worked.
- Anything realtime.

---

## §9 — Summary

| Status | Tickets |
|--------|---------|
| Ready to build as written | B1, B2, B3, B4 |
| Blocked on a product decision | A1, A3, A5, A6, A8, B5, D3, D4, D6, E3, E4 |
| Deferred to v2 | All of Epic C |

**Net scope change:** eight tickets out (Epic C), eleven in (Epics D + E) — and the plan's most expensive infrastructure item removed. The increase in effort is real but modest; the increase in signal quality, and the removal of an assumption that could have invalidated seven tickets, are not.

---

## The positioning consequence *(New)*

With Epic C deferred, Rafiqi sits **around** the lesson rather than **inside** it: it prepares the student before, studies with them after, and hands the teacher what it learned in between. That is a cleaner and more honest position than a product that competes for attention during instruction — but it needs to be stated deliberately, so we do not quietly re-introduce live features in three months' time.

The original plan builds three features that work. This review is about making them one product — and about spending v1 on the loop that runs every day, rather than the one that runs for forty minutes.
