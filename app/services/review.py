"""Deterministic review chat with persistent attempt and MVP mastery evidence."""
from copy import deepcopy
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import (
    MasteryRecord,
    ReviewAttempt,
    ReviewChapter,
    ReviewLesson,
    ReviewSession,
    ReviewSessionSummary,
)
from app.schemas.review import AttemptOut, LessonOut, Locale, MasteryOut, ReviewMessage, SessionOut
from app.services.review_assessment import AssessmentMetadataError, classify_error

# Idempotency keys only need to cover client retries, so the list is trimmed rather
# than grown forever — the events list has its own separate 1000-entry cap.
REQUEST_HISTORY_LIMIT = 200
MASTERY_CALCULATION_VERSION = "mvp-v1"

COPY = {
    "welcome": {"en": "Let’s review this lesson. Answer the question or ask me for help.", "ar": "لنراجع هذا الدرس. أجب عن السؤال أو اطلب مني المساعدة."},
    "correct": {"en": "Correct!", "ar": "إجابة صحيحة!"},
    "partial": {"en": "Partly correct. Try to explain which objects the forces act on.", "ar": "إجابة صحيحة جزئياً. حاول توضيح الجسم الذي تؤثر عليه كل قوة."},
    "retry": {"en": "Not quite yet. Try again or reveal a hint.", "ar": "ليست الإجابة المطلوبة بعد. حاول مرة أخرى أو اطلب تلميحاً."},
    "complete": {"en": "Review complete. You can still ask for help with this lesson.", "ar": "اكتملت المراجعة. يمكنك الاستمرار في طلب المساعدة في هذا الدرس."},
    "help": {"en": "Demo explanation: ", "ar": "شرح تجريبي: "},
}

SUMMARY_COPY = {
    "secure": {
        "en": "You showed a strong understanding of {concept}.",
        "ar": "أظهرت فهماً جيداً لمفهوم {concept}.",
    },
    "developing": {
        "en": "You are building your understanding of {concept}.",
        "ar": "أنت تطور فهمك لمفهوم {concept}.",
    },
    "needs_support": {
        "en": "Keep practising {concept}; it is not settled yet.",
        "ar": "استمر في التدريب على {concept}؛ ما زال يحتاج إلى تثبيت.",
    },
    "next_secure": {
        "en": "You are ready to continue to the next lesson.",
        "ar": "أنت مستعد للانتقال إلى الدرس التالي.",
    },
    "next_developing": {
        "en": "Review {concept} once more before moving on.",
        "ar": "راجع {concept} مرة أخرى قبل الانتقال.",
    },
    "next_needs_support": {
        "en": "Practise {concept} again and use the hints when you need them.",
        "ar": "تدرّب على {concept} مرة أخرى واستخدم التلميحات عند الحاجة.",
    },
}


def initial_state():
    return {"index": 0, "attempts": 0, "hint_level": 0, "assistance": False, "resolved": False,
            "complete": False, "events": [{"role": "assistant", "kind": "text", "copy": "welcome"}, {"role": "assistant", "kind": "question", "index": 0}],
            "requests": []}


class ReviewError(Exception):
    """Domain error. The route maps `status` to the HTTP code and reports `message`."""

    def __init__(self, code, status=409):
        super().__init__(code)
        self.code = code
        self.status = status
        self.message = code.replace("_", " ").capitalize()


def fail(detail, status=409):
    raise ReviewError(detail, status)


def is_help(text):
    return bool(re.search(r"\?|؟|\b(help|explain|hint|example|why|how|what|confused)\b|ساعد|اشرح|شرح|تلميح|مثال|لماذا|كيف|ما معنى|لا أفهم", text, re.I))


def localized_content(content, locale):
    if locale not in content:
        raise ReviewError("lesson_translation_unavailable", 409)
    return content[locale]


def apply_message(content, original, message: ReviewMessage):
    state = deepcopy(original)
    locale = message.locale
    question = localized_content(content, locale)["questions"][state["index"]]
    if message.question_id and message.question_id != question["id"]:
        fail("stale_question")
    action = message.action
    if action == "chat":
        action = "help" if is_help(message.text) or question["kind"] == "choice" or state["resolved"] or state["complete"] else "answer"
        if action == "answer" and not message.question_id:
            fail("chat_question_id_required")
    if state["complete"] and action not in ("help",):
        fail("review_complete")
    if action in ("answer", "hint", "next") and message.question_id != question["id"]:
        fail("question_required")
    events = state["events"]
    if len(events) >= 1000:
        fail("conversation_limit")
    if action == "next":
        if not state["resolved"]:
            fail("answer_pending")
        events.append({"role": "student", "kind": "action", "action": "next", "locale": locale})
        if state["index"] + 1 == len(content[locale]["questions"]):
            state["complete"] = True
            events.append({"role": "assistant", "kind": "complete", "copy": "complete"})
        else:
            state.update(index=state["index"] + 1, attempts=0, hint_level=0, assistance=False, resolved=False)
            events.append({"role": "assistant", "kind": "question", "index": state["index"]})
    elif action == "hint":
        if state["resolved"] or state["hint_level"] >= len(question["hints"]):
            fail("no_more_hints")
        state["hint_level"] += 1
        state["assistance"] = True
        events.append({"role": "student", "kind": "action", "action": "hint", "locale": locale})
        events.append({"role": "assistant", "kind": "hint", "question_id": question["id"],
                       "level": state["hint_level"], "locale": locale, "text": question["hints"][state["hint_level"] - 1]})
    elif action == "help":
        events.append({"role": "student", "kind": "text", "text": message.text.strip(), "locale": locale, "action": "help"})
        state["assistance"] = True
        events.append({"role": "assistant", "kind": "text", "locale": locale,
                       "text": COPY["help"][locale] + question["explanation"]})
    else:
        if state["resolved"] or state["attempts"] >= 3:
            fail("question_finished")
        text = message.text.strip()
        if question["kind"] == "choice":
            selected = next((o for o in question["options"] if o["id"] == message.option_id), None)
            if selected is None:
                fail("invalid_option", 422)
            text = selected["text"]
            score = float(message.option_id == question["answer"])
        else:
            if not text:
                fail("answer_required", 422)
            # Deliberately simple demo rubric, not a validated educational assessment.
            score = sum(any(term in text.lower() for term in group) for group in question["keywords"]) / len(question["keywords"])
        state["attempts"] += 1
        state["resolved"] = score == 1 or state["attempts"] == 3
        events.append({"role": "student", "kind": "answer", "question_id": question["id"], "locale": locale,
                       "text": text, "option_id": message.option_id, "attempt": state["attempts"],
                       "hint_level": state["hint_level"], "assisted": state["assistance"], "concept_ref": question.get("concept_ref")})
        feedback = COPY["correct" if score == 1 else "partial" if score else "retry"][locale]
        if state["resolved"]:
            feedback += " " + question["explanation"]
        events.append({"role": "assistant", "kind": "feedback", "question_id": question["id"],
                       "locale": locale, "text": feedback, "score": score, "attempt": state["attempts"], "concept_ref": question.get("concept_ref")})
    state["requests"] = [*state["requests"], str(message.request_id)][-REQUEST_HISTORY_LIMIT:]
    return state


def lesson_public(lesson_id, content, locale):
    data = localized_content(content, locale)
    return {"id": lesson_id, "subject_id": content["subject_id"], "chapter_id": content["chapter_id"],
            "concept_refs": data.get("concept_refs", []),
            **{key: data[key] for key in ("title", "subject", "chapter", "objective", "key_points")}}


def session_public(session, locale):
    state = session.state
    questions = localized_content(session.content, locale)["questions"]
    # Explicit allow-list: never serialize answer keys, keywords or unrevealed hints.
    visible = [{**{key: q[key] for key in ("id", "kind", "text", "options")}, "concept_ref": q.get("concept_ref")}
               for q in questions[:state["index"] + 1]]
    events = []
    for event in state["events"]:
        output = dict(event)
        if output["kind"] == "question":
            q = questions[output.pop("index")]
            output.update(text=q["text"], question_id=q["id"])
        if "copy" in output:
            output["text"] = COPY[output.pop("copy")][locale]
        events.append(output)
    return {"id": str(session.id), "lesson_id": session.lesson_id, "version": session.version,
            "lesson": lesson_public(session.lesson_id, session.content, locale),
            "mock": True, "complete": state["complete"], "current_question_id": questions[state["index"]]["id"],
            "attempts": state["attempts"], "hint_level": state["hint_level"], "resolved": state["resolved"],
            "can_hint": not state["complete"] and not state["resolved"] and state["hint_level"] < len(questions[state["index"]]["hints"]),
            "total_questions": len(questions), "questions": visible, "messages": events}


def summary_public(session: ReviewSession, summary: ReviewSessionSummary, locale: Locale) -> dict:
    content = localized_content(session.content, locale)
    titles = {item["id"]: item["title"] for item in content.get("concept_refs", [])}
    concepts = []
    for item in summary.concepts:
        title = titles.get(item["concept_ref"], item["concept_ref"])
        outcome = item["mastery_band"]
        concepts.append({
            "concept_ref": item["concept_ref"],
            "title": title,
            "outcome": outcome,
            "message": SUMMARY_COPY[outcome][locale].format(concept=title),
            "completed_with_support": item["completed_with_support"],
        })

    weakest = min(
        concepts,
        key=lambda item: {"needs_support": 0, "developing": 1, "secure": 2}[item["outcome"]],
    )
    next_key = {
        "needs_support": "next_needs_support",
        "developing": "next_developing",
        "secure": "next_secure",
    }[weakest["outcome"]]
    return {
        "id": summary.id,
        "session_id": summary.session_id,
        "lesson_id": summary.lesson_id,
        "lesson_title": content["title"],
        "concepts": concepts,
        "total_attempts": summary.total_attempts,
        "next_step": SUMMARY_COPY[next_key][locale].format(concept=weakest["title"]),
        "completed_at": summary.completed_at,
    }


# ── Persistence ───────────────────────────────────────────────────────────────

async def _owned_session(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    lesson_id: str | None = None,
    lock: bool = False,
) -> ReviewSession | None:
    """Look a session up by id or lesson, always scoped to the bearer-token student."""
    stmt = select(ReviewSession).where(
        ReviewSession.school_id == school_id,
        ReviewSession.student_id == student_id,
    )
    stmt = stmt.where(ReviewSession.id == session_id) if session_id else stmt.where(ReviewSession.lesson_id == lesson_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _owned_summary(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    session_id: uuid.UUID,
) -> ReviewSessionSummary | None:
    return (await db.execute(
        select(ReviewSessionSummary).where(
            ReviewSessionSummary.session_id == session_id,
            ReviewSessionSummary.student_id == student_id,
            ReviewSessionSummary.school_id == school_id,
        )
    )).scalar_one_or_none()


async def _session_out(
    db: AsyncSession,
    session: ReviewSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    locale: Locale,
) -> SessionOut:
    data = session_public(session, locale)
    if session.state["complete"]:
        summary = await _owned_summary(db, student_id, school_id, session.id)
        if summary is not None:
            data["summary"] = summary_public(session, summary, locale)
    return SessionOut(**data)


async def list_lessons(db: AsyncSession, locale: Locale, chapter_id: str | None = None) -> list[LessonOut]:
    statement = select(ReviewLesson).order_by(ReviewLesson.id)
    if chapter_id is not None:
        if await db.get(ReviewChapter, chapter_id) is None:
            raise ReviewError("chapter_not_found", 404)
        statement = statement.where(ReviewLesson.chapter_id == chapter_id)
    rows = (await db.execute(statement)).scalars().all()
    return [LessonOut(**lesson_public(row.id, row.content, locale)) for row in rows]


async def get_lesson(db: AsyncSession, lesson_id: str, locale: Locale) -> LessonOut:
    row = await db.get(ReviewLesson, lesson_id)
    if row is None:
        raise ReviewError("lesson_not_found", 404)
    return LessonOut(**lesson_public(row.id, row.content, locale))


async def create_or_resume_session(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, lesson_id: str, locale: Locale,
) -> tuple[SessionOut, bool]:
    """Return the student's session for this lesson plus whether this call created it."""
    existing = await _owned_session(db, student_id, school_id, lesson_id=lesson_id)
    if existing:
        return await _session_out(db, existing, student_id, school_id, locale), False

    lesson = await db.get(ReviewLesson, lesson_id)
    if lesson is None:
        raise ReviewError("lesson_not_found", 404)

    localized_content(lesson.content, locale)
    session = ReviewSession(school_id=school_id, student_id=student_id, lesson_id=lesson.id,
                            content=lesson.content, state=initial_state(), version=0)
    db.add(session)
    try:
        await db.commit()
        await db.refresh(session)
    except IntegrityError:
        # A concurrent create won the unique constraint — resume the row it wrote.
        await db.rollback()
        session = await _owned_session(db, student_id, school_id, lesson_id=lesson_id)
        if session is None:
            raise
        return await _session_out(db, session, student_id, school_id, locale), False
    return await _session_out(db, session, student_id, school_id, locale), True


async def get_session_by_lesson(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, lesson_id: str, locale: Locale,
) -> SessionOut:
    session = await _owned_session(db, student_id, school_id, lesson_id=lesson_id)
    if session is None:
        raise ReviewError("session_not_found", 404)
    return await _session_out(db, session, student_id, school_id, locale)


async def get_session(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, session_id: uuid.UUID, locale: Locale,
) -> SessionOut:
    session = await _owned_session(db, student_id, school_id, session_id=session_id)
    if session is None:
        raise ReviewError("session_not_found", 404)
    return await _session_out(db, session, student_id, school_id, locale)


async def list_attempts(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, session_id: uuid.UUID,
) -> list[AttemptOut]:
    if await _owned_session(db, student_id, school_id, session_id=session_id) is None:
        raise ReviewError("session_not_found", 404)
    rows = (await db.execute(
        select(ReviewAttempt).where(
            ReviewAttempt.session_id == session_id,
            ReviewAttempt.student_id == student_id,
            ReviewAttempt.school_id == school_id,
        ).order_by(ReviewAttempt.created_at, ReviewAttempt.id)
    )).scalars().all()
    return [AttemptOut.model_validate(row) for row in rows]


async def list_mastery(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID,
) -> list[MasteryOut]:
    rows = (await db.execute(
        select(MasteryRecord).where(
            MasteryRecord.student_id == student_id,
            MasteryRecord.school_id == school_id,
        ).order_by(MasteryRecord.subject_id, MasteryRecord.concept_ref)
    )).scalars().all()
    return [MasteryOut.model_validate(row) for row in rows]


def mastery_band(score: float) -> str:
    """Map the approved MVP score to its student-safe categorical band."""
    if score < 0.5:
        return "needs_support"
    if score < 0.8:
        return "developing"
    return "secure"


async def _recalculate_mastery(
    db: AsyncSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
    subject_id: str,
    concept_ref: str,
) -> None:
    """Rebuild one concept record from immutable attempts in the current transaction."""
    attempts = (await db.execute(
        select(ReviewAttempt)
        .join(ReviewLesson, ReviewLesson.id == ReviewAttempt.lesson_id)
        .join(ReviewChapter, ReviewChapter.id == ReviewLesson.chapter_id)
        .where(
            ReviewAttempt.student_id == student_id,
            ReviewAttempt.school_id == school_id,
            ReviewAttempt.concept_ref == concept_ref,
            ReviewChapter.subject_id == subject_id,
        )
        .order_by(ReviewAttempt.created_at, ReviewAttempt.id)
    )).scalars().all()
    if not attempts:
        return

    latest_by_question: dict[tuple[str, str], ReviewAttempt] = {}
    for attempt in attempts:
        latest_by_question[(attempt.lesson_id, attempt.question_id)] = attempt
    evidence = sorted(latest_by_question.values(), key=lambda row: (row.created_at, str(row.id)))
    score = sum(row.correctness_score for row in evidence) / len(evidence)
    unresolved_errors = [row for row in evidence if row.error_type is not None]
    dominant_error = unresolved_errors[-1].error_type if unresolved_errors else None

    values = {
        "id": uuid.uuid4(),
        "school_id": school_id,
        "student_id": student_id,
        "subject_id": subject_id,
        "concept_ref": concept_ref,
        "mastery_score": score,
        "mastery_band": mastery_band(score),
        "evidence_count": len(evidence),
        "attempt_count": len(attempts),
        "assisted_evidence_count": sum(row.assisted for row in evidence),
        "dominant_error_type": dominant_error,
        "calculation_version": MASTERY_CALCULATION_VERSION,
        "last_attempt_at": attempts[-1].created_at,
    }
    immutable_keys = {"id", "school_id", "student_id", "subject_id", "concept_ref"}
    update_values = {key: value for key, value in values.items() if key not in immutable_keys}
    update_values["updated_at"] = func.now()
    await db.execute(
        pg_insert(MasteryRecord)
        .values(**values)
        .on_conflict_do_update(constraint="uq_mastery_student_concept", set_=update_values)
    )


async def _complete_session(
    db: AsyncSession,
    session: ReviewSession,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
) -> None:
    """Refresh D4 and create the one immutable D6 summary in the same transaction."""
    if await _owned_summary(db, student_id, school_id, session.id) is not None:
        return

    attempts = (await db.execute(
        select(ReviewAttempt).where(
            ReviewAttempt.session_id == session.id,
            ReviewAttempt.student_id == student_id,
            ReviewAttempt.school_id == school_id,
        ).order_by(ReviewAttempt.created_at, ReviewAttempt.id)
    )).scalars().all()
    if not attempts:
        raise ReviewError("summary_evidence_required", 409)

    concept_refs = list(dict.fromkeys(row.concept_ref for row in attempts))
    subject_id = session.content["subject_id"]
    for concept_ref in concept_refs:
        await _recalculate_mastery(
            db=db,
            student_id=student_id,
            school_id=school_id,
            subject_id=subject_id,
            concept_ref=concept_ref,
        )

    mastery_rows = (await db.execute(
        select(MasteryRecord).where(
            MasteryRecord.student_id == student_id,
            MasteryRecord.school_id == school_id,
            MasteryRecord.subject_id == subject_id,
            MasteryRecord.concept_ref.in_(concept_refs),
        )
    )).scalars().all()
    mastery_by_concept = {row.concept_ref: row for row in mastery_rows}

    latest_evidence: dict[tuple[str, str], ReviewAttempt] = {}
    for attempt in attempts:
        latest_evidence[(attempt.concept_ref, attempt.question_id)] = attempt

    concepts = []
    for concept_ref in concept_refs:
        mastery = mastery_by_concept.get(concept_ref)
        if mastery is None:
            raise ReviewError("mastery_record_unavailable", 409)
        evidence = [
            row for (ref, _), row in latest_evidence.items() if ref == concept_ref
        ]
        concepts.append({
            "concept_ref": concept_ref,
            "mastery_band": mastery.mastery_band,
            "completed_with_support": any(row.assisted for row in evidence),
            "dominant_error_type": mastery.dominant_error_type,
        })

    db.add(ReviewSessionSummary(
        school_id=school_id,
        student_id=student_id,
        session_id=session.id,
        lesson_id=session.lesson_id,
        concepts=concepts,
        total_attempts=len(attempts),
        calculation_version=MASTERY_CALCULATION_VERSION,
    ))
    await db.flush()


def _attempt_from_events(
    session: ReviewSession,
    message: ReviewMessage,
    new_state: dict,
    previous_event_count: int,
    student_id: uuid.UUID,
    school_id: uuid.UUID,
) -> ReviewAttempt | None:
    added = new_state["events"][previous_event_count:]
    answer = next((event for event in added if event["kind"] == "answer"), None)
    if answer is None:
        return None
    feedback = next(event for event in added if event["kind"] == "feedback")
    questions = localized_content(session.content, message.locale)["questions"]
    question = next(item for item in questions if item["id"] == answer["question_id"])
    try:
        error_type = classify_error(
            subject_id=session.content.get("subject_id"),
            question=question,
            option_id=answer.get("option_id"),
            score=float(feedback["score"]),
        )
    except AssessmentMetadataError as error:
        raise ReviewError(str(error), 409) from error
    return ReviewAttempt(
        school_id=school_id,
        student_id=student_id,
        session_id=session.id,
        lesson_id=session.lesson_id,
        request_id=message.request_id,
        question_id=question["id"],
        concept_ref=question["concept_ref"],
        response_text=answer["text"],
        option_id=answer.get("option_id"),
        correctness_score=float(feedback["score"]),
        error_type=error_type,
        hint_level=answer["hint_level"],
        assisted=answer["assisted"],
        attempt_number=answer["attempt"],
        locale=answer["locale"],
    )


async def process_message(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, session_id: uuid.UUID, message: ReviewMessage,
) -> SessionOut:
    session = await _owned_session(db, student_id, school_id, session_id=session_id, lock=True)
    if session is None:
        raise ReviewError("session_not_found", 404)
    if str(message.request_id) in session.state["requests"]:
        return await _session_out(db, session, student_id, school_id, message.locale)
    if session.version != message.expected_version:
        raise ReviewError("stale_session", 409)

    was_complete = session.state["complete"]
    previous_event_count = len(session.state["events"])
    new_state = apply_message(session.content, session.state, message)
    attempt = _attempt_from_events(session, message, new_state, previous_event_count, student_id, school_id)
    session.state = new_state
    session.version += 1
    if attempt is not None:
        db.add(attempt)
        await db.flush()
        await _recalculate_mastery(
            db=db,
            student_id=student_id,
            school_id=school_id,
            subject_id=session.content["subject_id"],
            concept_ref=attempt.concept_ref,
        )
    if new_state["complete"] and not was_complete:
        await _complete_session(db, session, student_id, school_id)
    await db.commit()
    await db.refresh(session)
    return await _session_out(db, session, student_id, school_id, message.locale)
