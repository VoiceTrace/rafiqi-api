import json
import logging

from app.core.config import settings
from app.models.message import SafetyCategory
from app.services.llm import LLMError, chat_completion, parse_json_object

logger = logging.getLogger(__name__)

_CLASSIFIER_SYSTEM_PROMPT = """You are a safety classifier for messages sent by a school \
student (a minor) to an AI tutor chat. Read the student's message and decide if it shows \
a clear signal of one of these categories:

- self_harm: suicidal ideation, self-injury, wanting to disappear/die
- abuse: signs of physical, emotional, or sexual abuse by another person
- bullying: being bullied, harassed, or excluded by peers
- distress: significant emotional distress not covered above (e.g. severe anxiety, panic, \
family crisis)
- cheating: asking to be given answers/completed work to pass off as their own, or asking \
how to cheat on a test

Respond with strict JSON only, no other text: {"category": "<one of the values above, or \
null if none apply>"}. Only flag a category when the signal is clear — do not flag normal \
frustration, mild complaints about schoolwork, or ordinary curiosity."""


async def classify_message(text: str) -> SafetyCategory | None:
    """
    Deterministic branch point: the LLM only proposes a category, the caller
    (app/services/cave.py) is the code that decides what happens next — the
    model never chooses the response.

    Fails open (returns None / unflagged) on any classifier error rather than
    blocking the chat. This is a known MVP limitation, not a hardened
    fail-closed safety gate.
    """
    try:
        raw = await chat_completion(
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            model=settings.SAFETY_CLASSIFIER_MODEL,
            temperature=0.0,
            json_mode=True,
            max_tokens=20,
        )
        category = parse_json_object(raw).get("category")
    except (LLMError, json.JSONDecodeError, AttributeError) as exc:
        logger.warning("Safety classifier failed, defaulting to unflagged: %s", exc)
        return None

    if category is None:
        return None
    try:
        return SafetyCategory(category)
    except ValueError:
        logger.warning("Safety classifier returned unknown category: %r", category)
        return None


# Deterministic scripted replies — never model-generated. Keyed by category so
# the response a flagged student sees never depends on model discretion.
SAFETY_SCRIPTS: dict[SafetyCategory, str] = {
    SafetyCategory.SELF_HARM: (
        "Thank you for telling me. What you're feeling matters, and this isn't something "
        "to go through alone — I've let a trusted adult at your school know so they can "
        "check in with you. You deserve support from a real person right now."
    ),
    SafetyCategory.ABUSE: (
        "Thank you for trusting me with that. What you're describing isn't okay, and it's "
        "not your fault. I've made a trusted adult at your school aware so they can help — "
        "you deserve to be safe."
    ),
    SafetyCategory.BULLYING: (
        "I'm sorry you're going through that — no one should feel that way at school. "
        "I've let a trusted adult know so they can look into it and support you."
    ),
    SafetyCategory.DISTRESS: (
        "That sounds really hard, and I'm glad you shared it with me. I've made a trusted "
        "adult at your school aware so you can get some real support with this."
    ),
    SafetyCategory.CHEATING: (
        "I can't give you the answers or do the work for you — that wouldn't actually help "
        "you learn it. I'm happy to walk through it with you step by step instead, whenever "
        "you're ready."
    ),
}
