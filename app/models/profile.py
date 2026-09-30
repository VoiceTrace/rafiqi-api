import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CardKey(StrEnum):
    """
    The learner profile is exactly these 7 fixed cards — not an open
    vocabulary. Each student has at most one ProfileCard row per key. See
    app/schemas/profile.py's CARD_DEFINITIONS for the static per-card
    metadata (id, icon, title, captures) the frontend renders.
    """

    HOW_YOU_LEARN = "how_you_learn"
    WHERE_YOU_ARE = "where_you_are"
    WHAT_DRIVES_YOU = "what_drives_you"
    HOW_YOU_FEEL = "how_you_feel"
    STUDY_HABITS = "study_habits"
    LANGUAGE_AND_COMPANY = "language_and_company"
    YOUR_WORLD = "your_world"


class StudentProfile(Base):
    """
    Anchor record — one per student. Thin by design; the richness lives in ProfileCard rows.
    """

    __tablename__ = "student_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="student_profile")
    cards: Mapped[list["ProfileCard"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class ProfileCard(Base):
    """
    One row per (student, card_key) — at most 7 per student, one per fixed
    life-area card (see CardKey). `reading` is the single narrative Rafiqi
    currently believes for that card; each extraction pass that touches a
    card replaces it with a fresh, complete synthesis, not an append. A row
    only exists once there's real signal for that card — no row yet is the
    normal "still getting to know you" state, surfaced as `reading: null`
    by the API layer (see app/services/profile.py), not stored as an empty
    row here.

    confidence_score is internal only (0.0-1.0) — used purely to decide how
    much a single extraction pass is allowed to move an established
    reading (see app/services/profile_extraction.py). Never exposed via
    the API: the frontend gets exactly {id, icon, title, captures,
    reading} per card, no score, no confidence label, per the explicit
    "extract this and only this" contract.
    """

    __tablename__ = "profile_cards"
    __table_args__ = (
        UniqueConstraint("profile_id", "card_key", name="uq_profile_cards_profile_id_card_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )

    # Controlled vocabulary — exactly the 7 CardKey values, plain string in
    # DB per this project's usual pattern (app-layer StrEnum, no DB constraint).
    card_key: Mapped[str] = mapped_column(String(50), nullable=False)

    reading: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    profile: Mapped["StudentProfile"] = relationship(back_populates="cards")
    source_conversation: Mapped["Conversation | None"] = relationship(back_populates="cards")
    corrections: Mapped[list["ProfileCardCorrection"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )


class ProfileCardCorrection(Base):
    """
    A5: a student's "not quite me?" flag on a card's reading, with their
    reason. Immutable audit log — resolved synchronously in the same
    request (see app/services/profile.py), `resolution_note` records what
    the AI did about it. Kept even after resolution for A4-style
    trust/debuggability.
    """

    __tablename__ = "profile_card_corrections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    card: Mapped["ProfileCard"] = relationship(back_populates="corrections")
