"""
A1 — Profile data model tests.

No database connection required: these tests validate that the SQLAlchemy
models are correctly defined (columns, relationships, defaults) and that
the fixed 7-card vocabulary in the schema layer is correct.
"""
from app.models.profile import ProfileCard
from app.models.school import School
from app.models.user import User, UserRole
from app.schemas.profile import CARD_DEFINITIONS, CARD_KEY_BY_ID, CardKey


# ---------------------------------------------------------------------------
# Model structure
# ---------------------------------------------------------------------------

def test_school_has_required_columns():
    cols = {c.name for c in School.__table__.columns}
    assert {"id", "name", "created_at"} <= cols


def test_user_has_school_id_and_role():
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "school_id", "email", "role", "hashed_password"} <= cols


def test_profile_card_has_all_required_columns():
    cols = {c.name for c in ProfileCard.__table__.columns}
    assert {
        "id",
        "school_id",       # tenant scoping
        "profile_id",
        "source_conversation_id",  # A4: trace a card back to the conversation that touched it
        "card_key",
        "reading",
        "confidence_score",  # internal only — never exposed via the API
        "updated_at",
    } <= cols


def test_profile_card_school_id_is_indexed():
    indexes = {idx.name for idx in ProfileCard.__table__.indexes}
    assert "ix_profile_cards_school_id" in indexes


def test_profile_card_has_unique_constraint_on_profile_and_card_key():
    """At most one row per (student, card_key) — exactly 7 possible cards."""
    constraint_names = {c.name for c in ProfileCard.__table__.constraints}
    assert "uq_profile_cards_profile_id_card_key" in constraint_names


# ---------------------------------------------------------------------------
# Fixed 7-card vocabulary
# ---------------------------------------------------------------------------

def test_user_role_values():
    assert set(UserRole) == {"teacher", "student"}


def test_exactly_seven_cards():
    assert len(CardKey) == 7
    assert len(CARD_DEFINITIONS) == 7


def test_card_definitions_cover_every_key_with_no_duplicates():
    assert set(CARD_DEFINITIONS.keys()) == set(CardKey)


def test_card_ids_are_1_through_7_with_no_gaps_or_duplicates():
    ids = sorted(definition.id for definition in CARD_DEFINITIONS.values())
    assert ids == list(range(1, 8))


def test_card_key_by_id_is_the_exact_inverse_of_card_definitions():
    for card_key, definition in CARD_DEFINITIONS.items():
        assert CARD_KEY_BY_ID[definition.id] == card_key


def test_every_card_definition_has_non_empty_metadata():
    for definition in CARD_DEFINITIONS.values():
        assert definition.icon
        assert definition.title
        assert definition.captures
