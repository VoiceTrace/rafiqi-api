import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TraitCategory(StrEnum):
    PREFERENCES = "preferences"
    GOALS = "goals"
    WELLBEING = "wellbeing"
    STUDY_HABITS = "study_habits"
    SOCIAL = "social"
    CONTEXT = "context"


class ConfidenceLabel(StrEnum):
    CONFIDENT = "confident"
    STILL_FORMING = "still_forming"


# Controlled vocabulary for trait_key — enforced here at the app layer,
# stored as plain string in DB so new keys don't require a migration.
# A starting MVP set per category, not exhaustive — expand freely, no migration needed.
class TraitKey(StrEnum):
    # Preferences — "how you learn"
    VISUAL_LEARNER = "visual_learner"
    AUDITORY_LEARNER = "auditory_learner"
    CURIOUS = "curious"
    FOCUSED = "focused"
    COLLABORATIVE = "collaborative"
    INDEPENDENT = "independent"
    # Goals — "what drives you"
    GOAL_UNDERSTAND_DEEPLY = "goal_understand_deeply"
    GOAL_BUILD_CONFIDENCE = "goal_build_confidence"
    GOAL_IMPROVE_GRADES = "goal_improve_grades"
    GOAL_ENJOY_LEARNING = "goal_enjoy_learning"
    # Wellbeing — "how you feel"
    CONFIDENT_UNDER_PRESSURE = "confident_under_pressure"
    GETS_ANXIOUS_EASILY = "gets_anxious_easily"
    RESILIENT_AFTER_SETBACKS = "resilient_after_setbacks"
    POSITIVE_ABOUT_SCHOOL = "positive_about_school"
    # Study habits
    PREFERS_SHORT_SESSIONS = "prefers_short_sessions"
    STUDIES_LAST_MINUTE = "studies_last_minute"
    STUDIES_WITH_ROUTINE = "studies_with_routine"
    EASILY_DISTRACTED = "easily_distracted"
    # Social — "language & company"
    PREFERS_ARABIC = "prefers_arabic"
    PREFERS_ENGLISH = "prefers_english"
    PREFERS_STUDYING_WITH_FRIENDS = "prefers_studying_with_friends"
    CODE_SWITCHES_ARABIC_ENGLISH = "code_switches_arabic_english"
    # Context — "your world"
    SUPPORTIVE_HOME_ENVIRONMENT = "supportive_home_environment"
    LIMITED_STUDY_TIME_AT_HOME = "limited_study_time_at_home"
    HAS_SIBLINGS_STUDY_SUPPORT = "has_siblings_study_support"
    PREFERS_QUIET_STUDY_SPACE = "prefers_quiet_study_space"


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
