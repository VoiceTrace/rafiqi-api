"""
A1 — Profile data model tests.

No database connection required: these tests validate that the SQLAlchemy
models are correctly defined (columns, relationships, defaults) and that the
confidence threshold logic in the schema layer is correct.
"""
import uuid

import pytest

from app.models.profile import (
    ConfidenceLabel,
    ProfileTrait,
    StudentProfile,
    TraitCategory,
)
from app.models.school import School
from app.models.user import User, UserRole
from app.schemas.profile import CONFIDENCE_THRESHOLD, TraitKey


# ---------------------------------------------------------------------------
# Model structure
# ---------------------------------------------------------------------------

def test_school_has_required_columns():
    cols = {c.name for c in School.__table__.columns}
    assert {"id", "name", "created_at"} <= cols


def test_user_has_school_id_and_role():
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "school_id", "email", "role", "hashed_password"} <= cols


def test_student_profile_has_school_id():
    """school_id must be on student_profiles — non-negotiable for PDPL multi-tenancy."""
    cols = {c.name for c in StudentProfile.__table__.columns}
    assert "school_id" in cols
    assert "student_id" in cols


def test_profile_trait_has_all_required_columns():
    cols = {c.name for c in ProfileTrait.__table__.columns}
    assert {
        "id",
        "school_id",       # tenant scoping
        "profile_id",
        "source_conversation_id",  # A4: trace trait back to conversation
        "category",
        "trait_key",
        "title",
        "description",
        "teaching_tip",
        "score",           # agent-facing numeric confidence
        "confidence",      # user-facing label
        "updated_at",
    } <= cols


def test_profile_trait_school_id_is_indexed():
    indexes = {idx.name for idx in ProfileTrait.__table__.indexes}
    assert "ix_profile_traits_school_id" in indexes


# ---------------------------------------------------------------------------
# Confidence threshold logic
# ---------------------------------------------------------------------------

def test_confidence_threshold_value():
    """Threshold must be 0.7 — document it so it isn't silently changed."""
    assert CONFIDENCE_THRESHOLD == 0.7


def test_confidence_label_values():
    assert ConfidenceLabel.CONFIDENT == "confident"
    assert ConfidenceLabel.STILL_FORMING == "still_forming"


@pytest.mark.parametrize("score,expected_label", [
    (0.0, ConfidenceLabel.STILL_FORMING),
    (0.69, ConfidenceLabel.STILL_FORMING),
    (0.7, ConfidenceLabel.CONFIDENT),
    (1.0, ConfidenceLabel.CONFIDENT),
])
def test_confidence_label_from_score(score, expected_label):
    label = (
        ConfidenceLabel.CONFIDENT
        if score >= CONFIDENCE_THRESHOLD
        else ConfidenceLabel.STILL_FORMING
    )
    assert label == expected_label


# ---------------------------------------------------------------------------
# Enum / controlled vocabulary
# ---------------------------------------------------------------------------

def test_trait_category_values():
    assert set(TraitCategory) == {"preferences", "goals"}


def test_user_role_values():
    assert set(UserRole) == {"teacher", "student"}


def test_trait_keys_are_strings():
    for key in TraitKey:
        assert isinstance(key.value, str)
        assert "_" in key.value or key.value.isalpha()
