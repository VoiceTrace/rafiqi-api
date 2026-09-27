import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MessageRole(StrEnum):
    STUDENT = "student"
    RAFIQI = "rafiqi"


class SafetyCategory(StrEnum):
    SELF_HARM = "self_harm"
    BULLYING = "bullying"
    ABUSE = "abuse"
    DISTRESS = "distress"
    CHEATING = "cheating"


class ConversationMessage(Base):
    """
    One turn in a Cave chat (A2).

    flagged/flag_category are set by the safety classifier (deterministic
    code branch, not model discretion) and read by the teacher-facing
    /conversations/flags endpoint. Flagged turns are excluded from A3
    profile extraction — a crisis or cheating moment isn't a learning-style
    signal.
    """

    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)  # MessageRole
    content: Mapped[str] = mapped_column(Text, nullable=False)

    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flag_category: Mapped[str | None] = mapped_column(String(20), nullable=True)  # SafetyCategory

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
