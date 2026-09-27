import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.message import ConversationMessage
from app.models.profile import ConfidenceLabel, ProfileTrait, StudentProfile
from app.schemas.profile import CONFIDENCE_THRESHOLD, TraitCategory, TraitKey
from app.services.llm import LLMError, chat_completion, parse_json_object

logger = logging.getLogger(__name__)

# A3 promotion rule (v2): the model sees the *current* profile and proposes a
# target score for each trait it chooses to touch; code only clamps how far a
# single session can move an existing trait, so one noisy conversation can't
# flip it, but real signal still moves it — without the model flying blind
# against a fixed formula it can't see. A brand-new trait has no prior value
# to clamp against, so it's created at whatever the model proposes.
_MAX_SCORE_DELTA_PER_SESSION = 0.3

_ALLOWED_TRAIT_KEYS = {key.value for key in TraitKey}
_ALLOWED_CATEGORIES = {cat.value for cat in TraitCategory}

_EXTRACTION_SYSTEM_PROMPT = f"""You are reading a transcript of a conversation between a \
student and an AI tutor called Rafiqi, held to get to know how the student learns \
("Rafiqi's Cave"). You will be told what is already believed about this student (if \
anything), then given the new transcript. Decide what, if anything, to add or change.

Rules:
- For a trait_key with no existing entry: propose one only if the transcript gives real, \
specific signal for it. Don't guess to fill gaps.
- For a trait_key that already has an entry: only include it if this new conversation adds \
real signal — either reinforcing it (propose a score at or slightly above the current one) or \
contradicting/complicating it (propose a lower score and an updated description).
- If nothing in this conversation bears on an existing trait, leave it out of the JSON array \
entirely. Do NOT include it just to say nothing changed — there is no field for "no update" \
and no reason to mention a trait you're not updating. A description like "no new signal" or \
"remains unchanged" must never appear in your output; if you find yourself writing something \
like that, delete that observation from the array instead.
- `description` is a narrative read of the *student*, written fresh each time — never a note \
about your own extraction process or what did/didn't change this session.
- Never invent an observation the transcript doesn't support.

Respond as a JSON object: {{"observations": [...]}}. Each observation has exactly these fields:
- trait_key: one of {sorted(_ALLOWED_TRAIT_KEYS)}
- category: one of {sorted(_ALLOWED_CATEGORIES)}
- observed_score: a float from 0.0 to 1.0 — your target confidence for this trait after this \
conversation (for an existing trait, this is what you think the *new* value should move \
toward, not a delta)
- title: a short (3-6 word) display title
- description: one or two sentences, written as a narrative read for a teacher — paraphrase \
the student's own words, never quote them verbatim, and never restate anything alarming or \
identifying
- teaching_tip: one short, actionable sentence for a teacher, or null

Return {{"observations": []}} if nothing clear emerged. Respond with strict JSON only."""


# Deterministic backstop for the "leave it out if nothing changed" prompt
# instruction — catches the model narrating its own extraction process
# instead of describing the student (see extract_and_merge's usage).
_NO_OP_PHRASES = (
    "no new signal", "no change", "remains unchanged", "unchanged from",
    "nothing new", "previously noted", "previously observed", "no update",
)


def _is_no_op_description(description: str) -> bool:
    lowered = description.lower()
    return any(phrase in lowered for phrase in _NO_OP_PHRASES)


def _profile_context(existing_by_key: dict[str, ProfileTrait]) -> str:
    if not existing_by_key:
        return "You don't know this student yet — no traits recorded so far."
    lines = "\n".join(
        f"- {key} ({trait.confidence}, current score {trait.score:.2f}): {trait.description}"
        for key, trait in sorted(existing_by_key.items())
    )
    return f"What you currently believe about this student:\n{lines}"


async def extract_and_merge(conversation: Conversation, db: AsyncSession) -> list[ProfileTrait]:
    """
    A3: reads the conversation transcript and merges observations into the
    student's ProfileTrait rows. The model is shown the *current* profile
    state and asked to propose fills (for gaps) or changes (for existing
    traits the conversation actually bears on) — diff-based by construction,
    since the model is told to omit anything it has no reason to touch.
    Code only clamps how far a single session can move an existing score (see
    `_MAX_SCORE_DELTA_PER_SESSION`), as a stability guard the model itself
    doesn't need to reason about. Flagged (safety) turns are excluded from
    the transcript — a crisis/cheating moment isn't a learning-style signal.

    Returns the traits created or updated by this call (possibly empty, e.g.
    a short chat with no real signal) — the FE's "what Rafiqi learned about
    you today" moment at the end of a session.
    """
    messages_result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at)
    )
    transcript = "\n".join(
        f"{msg.role}: {msg.content}" for msg in messages_result.scalars().all() if not msg.flagged
    )
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

    existing_result = await db.execute(
        select(ProfileTrait).where(ProfileTrait.profile_id == profile.id)
    )
    existing_by_key = {trait.trait_key: trait for trait in existing_result.scalars().all()}

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
            max_tokens=1000,
        )
        observations = parse_json_object(raw).get("observations", [])
    except (LLMError, json.JSONDecodeError, AttributeError) as exc:
        logger.warning("Profile extraction failed for conversation %s: %s", conversation.id, exc)
        return []

    touched: list[ProfileTrait] = []

    for obs in observations:
        trait_key = obs.get("trait_key")
        category = obs.get("category")
        if trait_key not in _ALLOWED_TRAIT_KEYS or category not in _ALLOWED_CATEGORIES:
            logger.warning("Skipping extraction observation with unknown key/category: %r", obs)
            continue

        observed_score = max(0.0, min(1.0, float(obs.get("observed_score", 0.0))))
        title = obs.get("title") or trait_key.replace("_", " ").title()
        description = obs.get("description") or ""
        teaching_tip = obs.get("teaching_tip")

        if _is_no_op_description(description):
            # Prompt-only "leave it out if nothing changed" isn't 100% reliable —
            # observed the model include a trait anyway with a description that's
            # just commentary on its own extraction process (e.g. "no new signal,
            # remains unchanged"). That text would otherwise overwrite a real
            # description, so skip applying this observation rather than trust it.
            logger.warning(
                "Skipping no-op-looking extraction observation for trait_key=%s: %r",
                trait_key, description,
            )
            continue

        existing = existing_by_key.get(trait_key)
        if existing is None:
            score = observed_score
            trait = ProfileTrait(
                id=uuid.uuid4(),
                school_id=conversation.school_id,
                profile_id=profile.id,
                source_conversation_id=conversation.id,
                category=category,
                trait_key=trait_key,
                title=title,
                description=description,
                teaching_tip=teaching_tip,
                score=score,
                confidence=(
                    ConfidenceLabel.CONFIDENT
                    if score >= CONFIDENCE_THRESHOLD
                    else ConfidenceLabel.STILL_FORMING
                ),
            )
            db.add(trait)
            existing_by_key[trait_key] = trait
            touched.append(trait)
        else:
            delta = max(
                -_MAX_SCORE_DELTA_PER_SESSION,
                min(_MAX_SCORE_DELTA_PER_SESSION, observed_score - existing.score),
            )
            existing.score = max(0.0, min(1.0, existing.score + delta))
            existing.confidence = (
                ConfidenceLabel.CONFIDENT
                if existing.score >= CONFIDENCE_THRESHOLD
                else ConfidenceLabel.STILL_FORMING
            )
            existing.title = title
            existing.description = description
            existing.teaching_tip = teaching_tip
            existing.source_conversation_id = conversation.id
            touched.append(existing)

    await db.commit()
    # updated_at is server-generated (server_default/onupdate) — refresh so the
    # returned objects carry the real value rather than whatever was loaded
    # before this call (or nothing at all, for a newly-created row).
    for trait in touched:
        await db.refresh(trait)

    return touched
