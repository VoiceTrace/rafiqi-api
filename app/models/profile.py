import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TraitCategory(StrEnum):
    PREFERENCES = "preferences"
    GOALS = "goals"


class ConfidenceLabel(StrEnum):
    """Human-readable label shown in the UI."""
    CONFIDENT = "confident"
    STILL_FORMING = "still_forming"


class StudentProfile(Base):
    """
    Anchor record — one per student. Thin by design; the richness lives in ProfileTrait rows.
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
    traits: Mapped[list["ProfileTrait"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class ProfileTrait(Base):
    """
    One row per trait per student.

    score       — agent-facing float (0.0–1.0): how confident the LLM is
                  about this trait. Drives the confidence label.
    confidence  — user-facing label derived from score:
                  score >= 0.7 → "confident", else "still_forming".
                  Stored explicitly so it can be queried/displayed without
                  re-running the threshold logic everywhere.
    source_conversation_id — which Cave chat produced/last updated this trait
                  (needed for A4: teacher can see where a trait came from).
    """

    __tablename__ = "profile_traits"

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

    # What kind of trait this is — matches the two UI card sections
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # TraitCategory

    # Controlled vocabulary enforced at the app layer (Python StrEnum in schemas),
    # stored as a plain string so new trait types don't require a DB migration.
    trait_key: Mapped[str] = mapped_column(String(100), nullable=False)

    # Display fields — what the UI and teacher see
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    teaching_tip: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Confidence — agent-facing numeric + user-facing label (see docstring above)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConfidenceLabel.STILL_FORMING
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    profile: Mapped["StudentProfile"] = relationship(back_populates="traits")
    source_conversation: Mapped["Conversation | None"] = relationship(
        back_populates="traits"
    )
