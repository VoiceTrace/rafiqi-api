import json
import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode
from app.models.profile import ProfileCard, ProfileCardCorrection, StudentProfile
from app.schemas.profile import CARD_DEFINITIONS, CARD_KEY_BY_ID, CardKey, LearnerCardOut, LearnerModelOut
from app.services.llm import LLMError, chat_completion, parse_json_object

logger = logging.getLogger(__name__)

_FALLBACK_ACKNOWLEDGEMENT = (
    "Thanks for telling me — I've made a note and will pay closer attention to this."
)

_CORRECTION_SYSTEM_PROMPT = """A student has flagged one of Rafiqi's reads of them as wrong, \
with their own explanation of why. Given the current card reading and their explanation, write \
a revised reading. Respond with strict JSON only:

{"reading": "<revised narrative, second person ('you...'), 1-3 plain sentences, paraphrased, \
never quoting the student verbatim>", "confidence": <float 0.0-1.0 — usually lower than before \
since the student says the read is wrong, unless their explanation actually confirms it and \
just adds nuance>, "acknowledgement": "<one warm, non-clinical sentence to say back to the \
student>"}"""


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Card not found"}},
    )


def card_to_out(card: ProfileCard) -> LearnerCardOut:
    definition = CARD_DEFINITIONS[CardKey(card.card_key)]
    return LearnerCardOut(
        id=definition.id,
        icon=definition.icon,
        title=definition.title,
        captures=definition.captures,
        reading=card.reading,
    )


async def get_own_profile_view(
    student_id: uuid.UUID, school_id: uuid.UUID, db: AsyncSession
) -> LearnerModelOut:
    """
    A6: the student's own learner profile — always exactly the 7 fixed
    cards, in fixed order. `reading` is null for any card nothing has been
    extracted for yet (including every card, for a student who hasn't
    chatted at all) — the normal "still getting to know you" state, not an
    error or a broken response.
    """
    profile_result = await db.execute(
        select(StudentProfile).where(
            StudentProfile.student_id == student_id, StudentProfile.school_id == school_id
        )
    )
    profile = profile_result.scalar_one_or_none()

    existing_by_key: dict[str, ProfileCard] = {}
    if profile is not None:
        cards_result = await db.execute(select(ProfileCard).where(ProfileCard.profile_id == profile.id))
        existing_by_key = {card.card_key: card for card in cards_result.scalars().all()}

    cards = []
    for card_key in CardKey:  # fixed display order, ids 1-7
        definition = CARD_DEFINITIONS[card_key]
        existing = existing_by_key.get(card_key.value)
        cards.append(
            LearnerCardOut(
                id=definition.id,
                icon=definition.icon,
                title=definition.title,
                captures=definition.captures,
                reading=existing.reading if existing else None,
            )
        )
    return LearnerModelOut(cards=cards)


async def flag_card(
    card_id: int, student_id: uuid.UUID, school_id: uuid.UUID, reason: str, db: AsyncSession
) -> tuple[LearnerCardOut, str]:
    """
    A5: student flags a card's reading as wrong and explains why. Resolved
    synchronously (no job queue in this stack) — one LLM call decides the
    revised reading, and the correction is recorded either way as an audit
    trail (A4-style trust/debuggability).

    Fails safe on an LLM error: rather than leaving a disputed reading
    looking untouched, its internal confidence is conservatively knocked down.
    """
    card_key = CARD_KEY_BY_ID.get(card_id)
    if card_key is None:
        raise _not_found()

    result = await db.execute(
        select(ProfileCard)
        .join(StudentProfile, StudentProfile.id == ProfileCard.profile_id)
        .where(
            ProfileCard.card_key == card_key.value,
            ProfileCard.school_id == school_id,
            StudentProfile.student_id == student_id,
        )
    )
    card = result.scalar_one_or_none()
    if card is None:
        # Either an invalid id or nothing's been extracted for this card yet —
        # either way there's no reading to dispute.
        raise _not_found()

    verdict = None
    try:
        raw = await chat_completion(
            messages=[
                {"role": "system", "content": _CORRECTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "card_title": CARD_DEFINITIONS[card_key].title,
                            "current_reading": card.reading,
                            "student_reason": reason,
                        }
                    ),
                },
            ],
            model=settings.PROFILE_EXTRACTION_MODEL,
            temperature=0.0,
            json_mode=True,
            max_tokens=300,
        )
        verdict = parse_json_object(raw)
    except (LLMError, json.JSONDecodeError) as exc:
        logger.warning("Card correction resolution failed for card %s: %s", card.id, exc)

    if verdict:
        card.reading = verdict.get("reading") or card.reading
        new_confidence = verdict.get("confidence")
        if isinstance(new_confidence, (int, float)):
            card.confidence_score = max(0.0, min(1.0, float(new_confidence)))
        acknowledgement = verdict.get("acknowledgement") or _FALLBACK_ACKNOWLEDGEMENT
    else:
        card.confidence_score = max(0.0, card.confidence_score - 0.3)
        acknowledgement = _FALLBACK_ACKNOWLEDGEMENT

    db.add(
        ProfileCardCorrection(
            id=uuid.uuid4(),
            school_id=school_id,
            card_id=card.id,
            reason=reason,
            resolution_note=acknowledgement,
        )
    )
    await db.commit()
    await db.refresh(card)
    return card_to_out(card), acknowledgement
