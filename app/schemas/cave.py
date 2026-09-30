import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.profile import LearnerCardOut


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


class StartConversationIn(BaseModel):
    fresh: bool = Field(
        default=False,
        description="True forces a brand-new conversation even if the student's current "
        "one is still active (< 12h old) — for an explicit 'start over' action, as "
        "opposed to a plain app-open which should omit this field entirely and resume "
        "whatever's active. The old active conversation's unprocessed messages are "
        "still folded into a profile update first, same as when one goes dormant on "
        "its own — nothing is lost by starting fresh early.",
    )


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
    is_new: bool = Field(
        ...,
        description="False means the student's active conversation was resumed — "
        "`message` is its most recent turn, not a fresh greeting. The "
        "frontend should fetch GET /conversations/{id} for the full history "
        "rather than treating `message` as the only content in that case.",
    )


class SendMessageOut(BaseModel):
    message: CaveMessageOut
    updated_cards: list[LearnerCardOut] | None = Field(
        default=None,
        description="A3 runs automatically roughly every 20 messages in a "
        "conversation, not on every turn — populated only on the turn that "
        "actually triggered it (or null). Same shape as A6's GET "
        "/profiles/me cards, no score/confidence field.",
    )


class CaveConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    school_id: uuid.UUID
    started_at: datetime
    messages: list[CaveMessageOut]


class ConversationSummaryOut(BaseModel):
    id: uuid.UUID
    started_at: datetime
    last_message_at: datetime
    last_message_preview: str
    is_active: bool = Field(
        ...,
        description="Whether this is the conversation a plain POST /conversations "
        "would resume right now. Every conversation is resumable by id "
        "regardless of this flag — there is no 'closed' state.",
    )


class FlaggedMessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    student_name: str
    category: SafetyCategory
    content: str
    created_at: datetime
