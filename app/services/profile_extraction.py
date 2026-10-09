import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.message import ConversationMessage
from app.models.profile import ProfileCard, StudentProfile
from app.schemas.profile import CARD_DEFINITIONS, CardKey
from app.services.llm import LLMError, chat_completion, parse_json_object

logger = logging.getLogger(__name__)

# A3 promotion rule: the model sees the *current* reading (if any) for each
# card and proposes a fresh one plus a confidence estimate; code only clamps
# how far a single pass can move an established card's internal confidence
# (never shown to the student — used purely as a stability guard so one
# noisy pass can't flip an established reading). A brand-new card has no
# prior value to clamp against, so it's created at whatever the model proposes.
_MAX_CONFIDENCE_DELTA_PER_PASS = 0.3

_ALLOWED_CARD_KEYS = {key.value for key in CardKey}

# The exact mock_reading examples from the product spec, reused here as
# few-shot grounding for tone/length/format — not content to copy verbatim
# for any real student.
_EXAMPLE_READINGS: dict[CardKey, str] = {
    CardKey.HOW_YOU_LEARN: (
        "You learn best by trying first, then seeing the explanation. "
        "Diagrams click faster than long text."
    ),
    CardKey.WHERE_YOU_ARE: (
        "Strong on forces; still linking force to acceleration. "
        "A small gap on vectors carried over from last year."
    ),
    CardKey.WHAT_DRIVES_YOU: (
        "You aim for engineering. You push harder when a topic connects to real machines and cars."
    ),
    CardKey.HOW_YOU_FEEL: (
        "You get a bit anxious before tests. You respond better to encouragement than to pressure."
    ),
    CardKey.STUDY_HABITS: (
        "You focus best in short evening sessions — and you tend to stay quiet "
        "when stuck instead of asking."
    ),
    CardKey.LANGUAGE_AND_COMPANY: (
        "English is your second language, so you prefer clear, simple wording — "
        "and you learn well in a small group."
    ),
    CardKey.YOUR_WORLD: (
        "Into football and gaming. You like a friendly, direct tone and answers that get to the point."
    ),
}

_CARD_GUIDE = "\n".join(
    f'- {key.value}: {CARD_DEFINITIONS[key].captures}\n'
    f'  Tone/length example (not this student\'s real content): "{_EXAMPLE_READINGS[key]}"'
    for key in CardKey
)

_EXTRACTION_SYSTEM_PROMPT = f"""You are reading a transcript of a conversation between a \
student and an AI tutor called Rafiqi, held to get to know how the student learns \
("Rafiqi's Cave"). The student's learner profile has exactly these 7 fixed cards — you can \
only ever write to these, never invent a new one:

{_CARD_GUIDE}

You will be told the current reading for each card (if any), then given the new transcript. \
For each card the transcript gives real, specific signal about, write a fresh, complete \
reading — second person ("you..."), 1-3 plain sentences, matching the tone and length of the \
examples above. A reading is a full current synthesis, not a diff or an appended note: fold in \
whatever from the old reading is still true alongside anything new.

Rules:
- Only include a card if the transcript gives real, specific signal for it — most \
conversations won't touch most cards. Don't guess to fill gaps.
- If nothing in this conversation bears on a card that already has a reading, leave it out of \
the JSON array entirely. Do NOT include it just to say nothing changed — a reading like "no \
new signal" or "remains unchanged" must never appear in your output.
- where_you_are is about academic strengths/gaps specifically — only write to it if the \
conversation actually touched on schoolwork; most casual chats won't, and that's fine, leave \
it out rather than guess.
- Never invent anything the transcript doesn't support, and never quote the student verbatim \
or restate anything alarming or identifying — paraphrase.

Respond as a JSON object: {{"observations": [...]}}. Each observation has exactly these fields:
- card_key: one of {sorted(_ALLOWED_CARD_KEYS)}
- reading: the fresh narrative, as described above
- confidence: a float from 0.0 to 1.0 — how strongly the transcript (plus any prior signal) \
supports this reading

Return {{"observations": []}} if nothing clear emerged. Respond with strict JSON only."""


# Deterministic backstop for the "leave it out if nothing changed" prompt
# instruction — catches the model narrating its own extraction process
# instead of describing the student (see extract_and_merge's usage).
_NO_OP_PHRASES = (
    "no new signal", "no change", "remains unchanged", "unchanged from",
    "nothing new", "previously noted", "previously observed", "no update",
)


def _is_no_op_reading(reading: str) -> bool:
    lowered = reading.lower()
    return any(phrase in lowered for phrase in _NO_OP_PHRASES)


def _profile_context(existing_by_key: dict[str, ProfileCard]) -> str:
    if not existing_by_key:
        return "You don't know this student yet — no cards have a reading so far."
    lines = "\n".join(f"- {key}: {card.reading}" for key, card in sorted(existing_by_key.items()))
    return f"Current readings for this student:\n{lines}"


async def extract_and_merge(
    conversation: Conversation, db: AsyncSession, message_offset: int = 0
) -> list[ProfileCard] | None:
    """
    A3: reads conversation messages after `message_offset` and writes fresh
    readings into the student's ProfileCard rows — one of exactly 7 fixed
    cards (see CardKey), never an open vocabulary. The model is shown each
    card's *current* reading (if any) and asked to propose a fresh
    synthesis only for cards the transcript actually bears on — diff-based
    by construction, since the model is told to omit anything it has no
    reason to touch. Code only clamps how far a single pass can move an
    existing card's internal confidence (see `_MAX_CONFIDENCE_DELTA_PER_PASS`),
    as a stability guard the model itself doesn't need to reason about.
    Flagged (safety) turns are excluded from the transcript — a
    crisis/cheating moment isn't a learning-style signal.

    `message_offset` skips messages already folded into a previous pass —
    this runs periodically over a conversation's life (see cave.py's
    `_maybe_extract`), not just once at the end, so re-sending and
    re-processing the whole transcript every time would grow unboundedly
    and double-count already-applied signal.

    Return value distinguishes two different kinds of "nothing to report":
    - `[]` — the pass *completed* (possibly with zero real observations, or
      an empty/all-flagged slice) — caller should still advance its
      checkpoint, there's nothing left to retry.
    - `None` — the pass *failed* (LLM/parse error) — caller should NOT
      advance its checkpoint, so this slice is retried on the next trigger
      instead of silently skipped forever.
    """
    messages_result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at)
    )
    new_messages = messages_result.scalars().all()[message_offset:]
    transcript = "\n".join(f"{msg.role}: {msg.content}" for msg in new_messages if not msg.flagged)
    if not transcript.strip():
        return []

    profile_result = await db.execute(
        select(StudentProfile).where(StudentProfile.student_id == conversation.student_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        profile = StudentProfile(
            id=uuid.uuid4(),
            school_id=conversation.school_id,
            student_id=conversation.student_id,
        )
        db.add(profile)
        await db.flush()

    existing_result = await db.execute(select(ProfileCard).where(ProfileCard.profile_id == profile.id))
    existing_by_key = {card.card_key: card for card in existing_result.scalars().all()}

    try:
        raw = await chat_completion(
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{_profile_context(existing_by_key)}\n\nNew conversation:\n{transcript}",
                },
            ],
            model=settings.PROFILE_EXTRACTION_MODEL,
            temperature=0.0,
            json_mode=True,
            max_tokens=1200,
        )
        observations = parse_json_object(raw).get("observations", [])
    except (LLMError, json.JSONDecodeError, AttributeError) as exc:
        logger.warning("Profile extraction failed for conversation %s: %s", conversation.id, exc)
        return None

    touched: list[ProfileCard] = []

    for obs in observations:
        card_key = obs.get("card_key")
        if card_key not in _ALLOWED_CARD_KEYS:
            logger.warning("Skipping extraction observation with unknown card_key: %r", obs)
            continue

        reading = (obs.get("reading") or "").strip()
        if not reading:
            continue
        if _is_no_op_reading(reading):
            # Prompt-only "leave it out if nothing changed" isn't 100% reliable —
            # observed the model include a card anyway with a reading that's just
            # commentary on its own extraction process (e.g. "no new signal,
            # remains unchanged"). That text would otherwise overwrite a real
            # reading, so skip applying this observation rather than trust it.
            logger.warning(
                "Skipping no-op-looking extraction observation for card_key=%s: %r",
                card_key, reading,
            )
            continue

        observed_confidence = max(0.0, min(1.0, float(obs.get("confidence", 0.5))))

        existing = existing_by_key.get(card_key)
        if existing is None:
            card = ProfileCard(
                id=uuid.uuid4(),
                school_id=conversation.school_id,
                profile_id=profile.id,
                source_conversation_id=conversation.id,
                card_key=card_key,
                reading=reading,
                confidence_score=observed_confidence,
            )
            db.add(card)
            existing_by_key[card_key] = card
            touched.append(card)
        else:
            delta = max(
                -_MAX_CONFIDENCE_DELTA_PER_PASS,
                min(_MAX_CONFIDENCE_DELTA_PER_PASS, observed_confidence - existing.confidence_score),
            )
            existing.confidence_score = max(0.0, min(1.0, existing.confidence_score + delta))
            existing.reading = reading
            existing.source_conversation_id = conversation.id
            touched.append(existing)

    await db.commit()
    # updated_at is server-generated (server_default/onupdate) — refresh so the
    # returned objects carry the real value rather than whatever was loaded
    # before this call (or nothing at all, for a newly-created row).
    for card in touched:
        await db.refresh(card)

    return touched
