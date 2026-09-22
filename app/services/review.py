"""Deterministic mock chat. No production AI or mastery claims."""
from copy import deepcopy
import re
from fastapi import HTTPException
from app.schemas.review import ReviewMessage

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


def fail(detail, status=409):
    raise HTTPException(status_code=status, detail=detail)


def is_help(text):
    return bool(re.search(r"\?|؟|\b(help|explain|hint|example|why|how|what|confused)\b|ساعد|اشرح|شرح|تلميح|مثال|لماذا|كيف|ما معنى|لا أفهم", text, re.I))


def apply_message(content, original, message: ReviewMessage):
    state = deepcopy(original)
    locale = message.locale
    question = content[locale]["questions"][state["index"]]
    if message.question_id and message.question_id != question["id"]:
        fail("stale_question")
    action = message.action
    if action == "chat":
        action = "help" if is_help(message.text) or question["kind"] == "choice" or state["resolved"] or state["complete"] else "answer"
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
                       "hint_level": state["hint_level"], "assisted": state["assistance"]})
        feedback = COPY["correct" if score == 1 else "partial" if score else "retry"][locale]
        if state["resolved"]:
            feedback += " " + question["explanation"]
        events.append({"role": "assistant", "kind": "feedback", "question_id": question["id"],
                       "locale": locale, "text": feedback, "score": score, "attempt": state["attempts"]})
    state["requests"].append(str(message.request_id))
    return state


def lesson_public(lesson_id, content, locale):
    data = content[locale]
    return {"id": lesson_id, **{key: data[key] for key in ("title", "subject", "chapter", "objective", "key_points")}}


def session_public(session, locale):
    state = session.state
    questions = session.content[locale]["questions"]
    # Explicit allow-list: never serialize answer keys, keywords or unrevealed hints.
    visible = [{key: q[key] for key in ("id", "kind", "text", "options")}
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
            "can_hint": not state["complete"] and not state["resolved"] and state["hint_level"] < 3,
            "total_questions": len(questions), "questions": visible, "messages": events}
