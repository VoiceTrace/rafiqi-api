"""
A5/A6 tests — student-facing profile view + "not quite me?" correction.
No database required (mocked AsyncSession, matching this repo's convention).

Tests cover:
- get_own_profile_cards: empty list when no profile exists yet (not an error)
- flag_trait: 404 for a trait that isn't the caller's own (ownership/tenant isolation)
- flag_trait: applies the model's revised description/score/acknowledgement
- flag_trait: fails safe (conservative reset) when the LLM call errors
- StudentTraitCardOut never exposes a raw `score` field (A6 disclosure rule)
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.profile import ConfidenceLabel, ProfileTrait, ProfileTraitCorrection
from app.schemas.profile import CONFIDENCE_THRESHOLD, StudentTraitCardOut
from app.services import profile as profile_svc
from app.services.llm import LLMError

_TRAIT_KEY = "curious"


def _fake_trait(**overrides) -> ProfileTrait:
    trait = ProfileTrait(
        id=uuid.uuid4(),
        school_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        category="preferences",
        trait_key=_TRAIT_KEY,
        title="Curious",
        description="Asks a lot of follow-up questions.",
        score=0.8,
        confidence=ConfidenceLabel.CONFIDENT,
    )
    for key, value in overrides.items():
        setattr(trait, key, value)
    return trait


# ---------------------------------------------------------------------------
# get_own_profile_cards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_own_profile_cards_empty_when_no_profile():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    cards = await profile_svc.get_own_profile_cards(uuid.uuid4(), uuid.uuid4(), mock_db)

    assert cards == []


@pytest.mark.asyncio
async def test_get_own_profile_cards_returns_traits():
    trait = _fake_trait()
    fake_profile = MagicMock()
    fake_profile.id = trait.profile_id

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = fake_profile
    traits_result = MagicMock()
    traits_result.scalars.return_value.all.return_value = [trait]

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [profile_result, traits_result]

    cards = await profile_svc.get_own_profile_cards(uuid.uuid4(), uuid.uuid4(), mock_db)

    assert cards == [trait]


# ---------------------------------------------------------------------------
# flag_trait: ownership / tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_trait_not_owned_raises_404():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # join excluded it — not this student's trait
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await profile_svc.flag_trait(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "that's not me", mock_db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# flag_trait: applies the model's verdict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_trait_applies_llm_verdict():
    trait = _fake_trait(score=0.8, confidence=ConfidenceLabel.CONFIDENT)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = trait
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()

    verdict = json.dumps(
        {
            "description": "Actually mostly curious about topics they already like.",
            "teaching_tip": "Let them pick the angle in.",
            "score": 0.4,
            "acknowledgement": "Good to know — I'll be more specific next time!",
        }
    )

    with patch("app.services.profile.chat_completion", new=AsyncMock(return_value=verdict)):
        updated, acknowledgement = await profile_svc.flag_trait(
            trait.id, uuid.uuid4(), uuid.uuid4(), "I'm only curious about football, not school stuff", mock_db
        )

    assert updated.score == 0.4
    assert updated.confidence == ConfidenceLabel.STILL_FORMING  # dropped below the 0.7 threshold
    assert updated.description == "Actually mostly curious about topics they already like."
    assert acknowledgement == "Good to know — I'll be more specific next time!"

    correction = next(
        call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], ProfileTraitCorrection)
    )
    assert correction.trait_id == trait.id
    assert correction.reason == "I'm only curious about football, not school stuff"
    assert correction.resolution_note == acknowledgement
    mock_db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# flag_trait: fails safe when the LLM errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_trait_falls_back_conservatively_on_llm_error():
    trait = _fake_trait(score=0.9, confidence=ConfidenceLabel.CONFIDENT)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = trait
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()

    with patch("app.services.profile.chat_completion", new=AsyncMock(side_effect=LLMError("down"))):
        updated, acknowledgement = await profile_svc.flag_trait(
            trait.id, uuid.uuid4(), uuid.uuid4(), "not me at all", mock_db
        )

    assert updated.score < CONFIDENCE_THRESHOLD  # conservatively knocked back
    assert updated.confidence == ConfidenceLabel.STILL_FORMING
    assert acknowledgement == profile_svc._FALLBACK_ACKNOWLEDGEMENT
    mock_db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# A6 disclosure rule: no raw score in the student-facing schema
# ---------------------------------------------------------------------------

def test_student_trait_card_out_has_no_score_field():
    assert "score" not in StudentTraitCardOut.model_fields
