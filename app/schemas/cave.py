import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.profile import StudentTraitCardOut


class MessageRole(StrEnum):
    STUDENT = "student"
    RAFIQI = "rafiqi"


class SafetyCategory(StrEnum):
    SELF_HARM = "self_harm"
    BULLYING = "bullying"
    ABUSE = "abuse"
    DISTRESS = "distress"
    CHEATING = "cheating"


class CaveMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class CaveMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    flagged: bool
    flag_category: SafetyCategory | None
    created_at: datetime


class ConversationStartOut(BaseModel):
    conversation_id: uuid.UUID
    message: CaveMessageOut


class CaveConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    school_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    messages: list[CaveMessageOut]


class ConversationEndOut(BaseModel):
    """
    A3, surfaced directly: what Rafiqi learned about the student from *this*
    conversation specifically — not the student's whole profile. Empty when
    the conversation gave no real signal (e.g. very short, or every message
    was safety-flagged and excluded). Same narrative-only shape as A6's
    GET /profiles/me — no `score` field, per the disclosure rule.
    """

    updated_traits: list[StudentTraitCardOut]


class FlaggedMessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    student_name: str
    category: SafetyCategory
    content: str
    created_at: datetime
