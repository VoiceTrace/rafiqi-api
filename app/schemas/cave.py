import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class FlaggedMessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    student_name: str
    category: SafetyCategory
    content: str
    created_at: datetime
