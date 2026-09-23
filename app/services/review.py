"""Deterministic mock chat. No production AI or mastery claims."""
from copy import deepcopy
import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewChapter, ReviewLesson, ReviewSession
from app.schemas.review import LessonOut, Locale, ReviewMessage, SessionOut

# Idempotency keys only need to cover client retries, so the list is trimmed rather
# than grown forever — the events list has its own separate 1000-entry cap.
REQUEST_HISTORY_LIMIT = 200

COPY = {
    "welcome": {"en": "Let’s review this lesson. Answer the question or ask me for help.", "ar": "لنراجع هذا الدرس. أجب عن السؤال أو اطلب مني المساعدة."},
    "correct": {"en": "Correct!", "ar": "إجابة صحيحة!"},
    "partial": {"en": "Partly correct. Try to explain which objects the forces act on.", "ar": "إجابة صحيحة جزئياً. حاول توضيح الجسم الذي تؤثر عليه كل قوة."},
    "retry": {"en": "Not quite yet. Try again or reveal a hint.", "ar": "ليست الإجابة المطلوبة بعد. حاول مرة أخرى أو اطلب تلميحاً."},
    "complete": {"en": "Review complete. You can still ask for help with this lesson.", "ar": "اكتملت المراجعة. يمكنك الاستمرار في طلب المساعدة في هذا الدرس."},
    "help": {"en": "Demo explanation: ", "ar": "شرح تجريبي: "},
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
        return SessionOut(**session_public(existing, locale)), False

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
        return SessionOut(**session_public(session, locale)), False
    return SessionOut(**session_public(session, locale)), True


async def get_session_by_lesson(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, lesson_id: str, locale: Locale,
) -> SessionOut:
    session = await _owned_session(db, student_id, school_id, lesson_id=lesson_id)
    if session is None:
        raise ReviewError("session_not_found", 404)
    return SessionOut(**session_public(session, locale))


async def get_session(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, session_id: uuid.UUID, locale: Locale,
) -> SessionOut:
    session = await _owned_session(db, student_id, school_id, session_id=session_id)
    if session is None:
        raise ReviewError("session_not_found", 404)
    return SessionOut(**session_public(session, locale))


async def process_message(
    db: AsyncSession, student_id: uuid.UUID, school_id: uuid.UUID, session_id: uuid.UUID, message: ReviewMessage,
) -> SessionOut:
    session = await _owned_session(db, student_id, school_id, session_id=session_id, lock=True)
    if session is None:
        raise ReviewError("session_not_found", 404)
    if str(message.request_id) in session.state["requests"]:
        return SessionOut(**session_public(session, message.locale))
    if session.version != message.expected_version:
        raise ReviewError("stale_session", 409)

    session.state = apply_message(session.content, session.state, message)
    session.version += 1
    await db.commit()
    await db.refresh(session)
    return SessionOut(**session_public(session, message.locale))
