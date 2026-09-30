from enum import StrEnum

from pydantic import BaseModel, Field


class CardKey(StrEnum):
    """
    The learner profile is exactly these 7 fixed cards — not an open
    vocabulary. See CARD_DEFINITIONS below for the static per-card metadata
    (id, icon, title, captures) the frontend renders alongside each reading.
    """

    HOW_YOU_LEARN = "how_you_learn"
    WHERE_YOU_ARE = "where_you_are"
    WHAT_DRIVES_YOU = "what_drives_you"
    HOW_YOU_FEEL = "how_you_feel"
    STUDY_HABITS = "study_habits"
    LANGUAGE_AND_COMPANY = "language_and_company"
    YOUR_WORLD = "your_world"


class CardDefinition(BaseModel):
    id: int
    icon: str
    title: str
    captures: str


# Static per-card metadata — identical for every student, never AI-generated.
# Iteration order here is the fixed display order (id 1-7).
CARD_DEFINITIONS: dict[CardKey, CardDefinition] = {
    CardKey.HOW_YOU_LEARN: CardDefinition(
        id=1, icon="🧭", title="How you learn",
        captures="Learning style: trying first vs. seeing the explanation first, diagrams vs. long text",
    ),
    CardKey.WHERE_YOU_ARE: CardDefinition(
        id=2, icon="📈", title="Where you are",
        captures="Academic level: strengths, current sticking points, and gaps carried over from earlier years",
    ),
    CardKey.WHAT_DRIVES_YOU: CardDefinition(
        id=3, icon="🎯", title="What drives you",
        captures="Goals and motivation, e.g. career aim and what topics make the student push harder",
    ),
    CardKey.HOW_YOU_FEEL: CardDefinition(
        id=4, icon="💙", title="How you feel",
        captures="Emotional side: test anxiety, and whether encouragement or pressure works better",
    ),
    CardKey.STUDY_HABITS: CardDefinition(
        id=5, icon="⏰", title="Your study habits",
        captures="Best time of day, session length, and behaviour when stuck (e.g. stays quiet instead of asking)",
    ),
    CardKey.LANGUAGE_AND_COMPANY: CardDefinition(
        id=6, icon="🌍", title="Language & company",
        captures="Language background, preference for simple wording, and whether they learn better "
        "alone or in a small group",
    ),
    CardKey.YOUR_WORLD: CardDefinition(
        id=7, icon="⚽", title="Your world",
        captures="Interests (football, gaming) and preferred tone: friendly, direct, to the point",
    ),
}

CARD_KEY_BY_ID: dict[int, CardKey] = {
    definition.id: key for key, definition in CARD_DEFINITIONS.items()
}


# ---------------------------------------------------------------------------
# A6 — student-facing view.
#
# Exactly the frontend contract, nothing else: id, icon, title, captures,
# reading. No numeric score, no confidence label — per the explicit
# "extract this and only this" spec. Never widen this without a new,
# explicit decision to do so.
# ---------------------------------------------------------------------------

class LearnerCardOut(BaseModel):
    id: int
    icon: str
    title: str
    captures: str
    reading: str | None = Field(
        default=None,
        description="Null until the first extraction pass produces real signal for this "
        "card — the normal 'still getting to know you' state, not an error.",
    )


class LearnerModelOut(BaseModel):
    cards: list[LearnerCardOut]


class ProfileViewOut(BaseModel):
    learner_model: LearnerModelOut


# ---------------------------------------------------------------------------
# A5 — "not quite me?" correction
# ---------------------------------------------------------------------------

class CardFlagIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class CardFlagOut(BaseModel):
    card: LearnerCardOut
    acknowledgement: str
