import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    """
    A Cave chat thread (A2 populates this). Never explicitly "ended" — a
    student can resume any of their conversations at any time. Exactly one
    conversation is treated as "active" at a time (see app/services/cave.py's
    `_ACTIVE_WINDOW`), based purely on how recently it was last touched, not
    on any stored state here.

    Exists here so ProfileCard.source_conversation_id (A4) has something to
    FK against.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # A3 checkpoint: how many of this conversation's messages have already
    # been folded into a profile-extraction pass. Extraction only processes
    # messages after this count (see profile_extraction.extract_and_merge's
    # `message_offset`) — without it, a long-running conversation would
    # resend and reprocess its entire transcript every 20 turns forever.
    last_extracted_message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    student: Mapped["User"] = relationship(back_populates="conversations")
    cards: Mapped[list["ProfileCard"]] = relationship(back_populates="source_conversation")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )
