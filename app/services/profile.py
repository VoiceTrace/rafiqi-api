import json
import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode
from app.models.profile import ConfidenceLabel, ProfileTrait, ProfileTraitCorrection, StudentProfile
from app.schemas.profile import CONFIDENCE_THRESHOLD
from app.services.llm import LLMError, chat_completion

logger = logging.getLogger(__name__)

_FALLBACK_ACKNOWLEDGEMENT = (
    "Thanks for telling me — I've made a note and will pay closer attention to this."
)

_CORRECTION_SYSTEM_PROMPT = """A student has flagged one of Rafiqi's reads of them as wrong, \
with their own explanation of why. Given the current trait card and their explanation, decide \
how to revise it. Respond with strict JSON only:

{"description": "<revised 1-2 sentence narrative, paraphrased, never quoting the student \
verbatim>", "teaching_tip": "<revised short tip for a teacher, or null>", "score": <float \
0.0-1.0, the corrected confidence — usually lower than before since the student says the read \
is wrong, unless their explanation actually confirms the read and just adds nuance>, \
"acknowledgement": "<one warm, non-clinical sentence to say back to the student>"}"""


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": ErrorCode.NOT_FOUND, "message": "Trait not found"}},
    )


async def get_own_profile_cards(
    student_id: uuid.UUID, school_id: uuid.UUID, db: AsyncSession
) -> list[ProfileTrait]:
    """
    A6: the student's own profile, narrative view. Returns an empty list for a
    student who hasn't chatted yet — the "new, not broken" empty state is a
    frontend concern, not a backend error.
    """
    profile_result = await db.execute(
        select(StudentProfile).where(
            StudentProfile.student_id == student_id, StudentProfile.school_id == school_id
        )
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        return []

    traits_result = await db.execute(
        select(ProfileTrait)
        .where(ProfileTrait.profile_id == profile.id)
        .order_by(ProfileTrait.category, ProfileTrait.trait_key)
    )
    return list(traits_result.scalars().all())


async def flag_trait(
    trait_id: uuid.UUID, student_id: uuid.UUID, school_id: uuid.UUID, reason: str, db: AsyncSession
) -> tuple[ProfileTrait, str]:
    """
    A5: student flags a trait card as wrong and explains why. Resolved
    synchronously (no job queue in this stack) — one LLM call decides whether
    to revise the description/tip/score, and the correction is recorded
    either way as an audit trail (A4-style trust/debuggability).

    Fails safe on an LLM error: rather than leaving a disputed trait looking
    untouched, it's conservatively knocked back to "still_forming".
    """
    result = await db.execute(
        select(ProfileTrait)
        .join(StudentProfile, StudentProfile.id == ProfileTrait.profile_id)
        .where(
            ProfileTrait.id == trait_id,
            ProfileTrait.school_id == school_id,
            StudentProfile.student_id == student_id,
        )
    )
    trait = result.scalar_one_or_none()
    if trait is None:
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
                            "trait_key": trait.trait_key,
                            "current_title": trait.title,
                            "current_description": trait.description,
                            "current_score": trait.score,
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
        verdict = json.loads(raw)
    except (LLMError, json.JSONDecodeError) as exc:
        logger.warning("Trait correction resolution failed for trait %s: %s", trait_id, exc)

    if verdict:
        trait.description = verdict.get("description") or trait.description
        trait.teaching_tip = verdict.get("teaching_tip", trait.teaching_tip)
        new_score = verdict.get("score")
        if isinstance(new_score, (int, float)):
            trait.score = max(0.0, min(1.0, float(new_score)))
        acknowledgement = verdict.get("acknowledgement") or _FALLBACK_ACKNOWLEDGEMENT
    else:
        trait.score = min(trait.score, CONFIDENCE_THRESHOLD - 0.05)
        acknowledgement = _FALLBACK_ACKNOWLEDGEMENT

    trait.confidence = (
        ConfidenceLabel.CONFIDENT if trait.score >= CONFIDENCE_THRESHOLD else ConfidenceLabel.STILL_FORMING
    )

    db.add(
        ProfileTraitCorrection(
            id=uuid.uuid4(),
            school_id=school_id,
            trait_id=trait.id,
            reason=reason,
            resolution_note=acknowledgement,
        )
    )
    await db.commit()
    await db.refresh(trait)
    return trait, acknowledgement
