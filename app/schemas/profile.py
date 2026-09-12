import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TraitCategory(StrEnum):
    PREFERENCES = "preferences"
    GOALS = "goals"


class ConfidenceLabel(StrEnum):
    CONFIDENT = "confident"
    STILL_FORMING = "still_forming"


# Controlled vocabulary for trait_key — enforced here at the app layer,
# stored as plain string in DB so new keys don't require a migration.
class TraitKey(StrEnum):
    # Preferences
    VISUAL_LEARNER = "visual_learner"
    AUDITORY_LEARNER = "auditory_learner"
    CURIOUS = "curious"
    FOCUSED = "focused"
    COLLABORATIVE = "collaborative"
    INDEPENDENT = "independent"
    # Goals
    GOAL_UNDERSTAND_DEEPLY = "goal_understand_deeply"
    GOAL_BUILD_CONFIDENCE = "goal_build_confidence"
    GOAL_IMPROVE_GRADES = "goal_improve_grades"
    GOAL_ENJOY_LEARNING = "goal_enjoy_learning"


CONFIDENCE_THRESHOLD = 0.7  # score >= this → "confident"


class ProfileTraitOut(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    source_conversation_id: uuid.UUID | None
    category: TraitCategory
    trait_key: str
    title: str
    description: str
    teaching_tip: str | None
    score: float = Field(ge=0.0, le=1.0)
    confidence: ConfidenceLabel
    updated_at: datetime

    model_config = {"from_attributes": True}


class StudentProfileOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    traits: list[ProfileTraitOut]

    model_config = {"from_attributes": True}
