"""
A5/A6 tests — student-facing learner profile view + "not quite me?" correction.
No database required (mocked AsyncSession, matching this repo's convention).

Tests cover:
- get_own_profile_view: always returns exactly 7 cards, in fixed order,
  with null readings/confidence when nothing's been extracted (no profile
  at all, or a profile missing some cards)
- flag_card: 404 for an invalid card id, and for a card nothing's been
  extracted for yet (own or otherwise)
- flag_card: applies the model's revised reading/confidence/acknowledgement
- flag_card: fails safe (confidence knocked down) when the LLM call errors
- confidence_level_from_score: the low/quiet/confident thresholds
- LearnerCardOut exposes a qualitative confidence label, never the raw
  score (A6 disclosure rule)
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.profile import ProfileCard, ProfileCardCorrection
from app.schemas.profile import (
    CARD_DEFINITIONS,
    CardKey,
    ConfidenceLevel,
    LearnerCardOut,
    confidence_level_from_score,
)
from app.services import profile as profile_svc
from app.services.llm import LLMError

_CARD_KEY = CardKey.HOW_YOU_LEARN


def _fake_card(**overrides) -> ProfileCard:
    card = ProfileCard(
        id=uuid.uuid4(),
        school_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        card_key=_CARD_KEY.value,
        reading="You learn best by trying things yourself first.",
        confidence_score=0.8,
    )
    for key, value in overrides.items():
        setattr(card, key, value)
    return card


# ---------------------------------------------------------------------------
# get_own_profile_view
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_own_profile_view_all_null_when_no_profile():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    view = await profile_svc.get_own_profile_view(uuid.uuid4(), uuid.uuid4(), mock_db)

    assert len(view.cards) == 7
    assert all(card.reading is None for card in view.cards)
    assert all(card.confidence is None for card in view.cards)


@pytest.mark.asyncio
async def test_get_own_profile_view_is_always_seven_cards_in_fixed_order():
    card = _fake_card()
    fake_profile = MagicMock()
    fake_profile.id = card.profile_id

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = fake_profile
    cards_result = MagicMock()
    cards_result.scalars.return_value.all.return_value = [card]  # only 1 of 7 has data

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [profile_result, cards_result]

    view = await profile_svc.get_own_profile_view(uuid.uuid4(), uuid.uuid4(), mock_db)

    assert [c.id for c in view.cards] == [1, 2, 3, 4, 5, 6, 7]  # fixed display order
    assert [c.title for c in view.cards] == [d.title for d in CARD_DEFINITIONS.values()]

    how_you_learn = next(c for c in view.cards if c.id == CARD_DEFINITIONS[_CARD_KEY].id)
    assert how_you_learn.reading == card.reading
    assert how_you_learn.confidence == ConfidenceLevel.CONFIDENT  # score=0.8 from _fake_card
    others = [c for c in view.cards if c.id != CARD_DEFINITIONS[_CARD_KEY].id]
    assert all(c.reading is None for c in others)  # untouched cards stay null, not missing
    assert all(c.confidence is None for c in others)


# ---------------------------------------------------------------------------
# flag_card: validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_card_invalid_id_raises_404():
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await profile_svc.flag_card(99, uuid.uuid4(), uuid.uuid4(), "not me", mock_db)

    assert exc_info.value.status_code == 404
    mock_db.execute.assert_not_awaited()  # never even queries for an out-of-range id


@pytest.mark.asyncio
async def test_flag_card_not_owned_or_not_extracted_yet_raises_404():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # join excluded it, or no reading yet
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await profile_svc.flag_card(1, uuid.uuid4(), uuid.uuid4(), "that's not me", mock_db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# flag_card: applies the model's verdict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_card_applies_llm_verdict():
    card = _fake_card(confidence_score=0.8)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = card
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()

    verdict = json.dumps(
        {
            "reading": "You actually prefer seeing a worked example before trying it yourself.",
            "confidence": 0.4,
            "acknowledgement": "Good to know — I'll adjust how I explain things.",
        }
    )

    with patch("app.services.profile.chat_completion", new=AsyncMock(return_value=verdict)):
        updated, acknowledgement = await profile_svc.flag_card(
            CARD_DEFINITIONS[_CARD_KEY].id, uuid.uuid4(), uuid.uuid4(),
            "I actually like seeing examples first", mock_db,
        )

    assert isinstance(updated, LearnerCardOut)
    assert updated.reading == "You actually prefer seeing a worked example before trying it yourself."
    assert acknowledgement == "Good to know — I'll adjust how I explain things."
    assert card.confidence_score == 0.4  # internal raw score
    assert updated.confidence == ConfidenceLevel.QUIET  # 0.4 -> the derived label, not 0.4 itself

    correction = next(
        call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], ProfileCardCorrection)
    )
    assert correction.card_id == card.id
    assert correction.reason == "I actually like seeing examples first"
    assert correction.resolution_note == acknowledgement
    mock_db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# flag_card: fails safe when the LLM errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_card_falls_back_conservatively_on_llm_error():
    card = _fake_card(confidence_score=0.9)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = card
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()

    original_reading = card.reading

    with patch("app.services.profile.chat_completion", new=AsyncMock(side_effect=LLMError("down"))):
        updated, acknowledgement = await profile_svc.flag_card(
            CARD_DEFINITIONS[_CARD_KEY].id, uuid.uuid4(), uuid.uuid4(), "not me at all", mock_db
        )

    assert card.confidence_score == pytest.approx(0.6)  # conservatively knocked down by 0.3
    assert updated.reading == original_reading  # left as-is, not overwritten with nothing
    assert acknowledgement == profile_svc._FALLBACK_ACKNOWLEDGEMENT
    assert updated.confidence == ConfidenceLevel.QUIET  # 0.9 - 0.3 = 0.6, still in the QUIET band
    mock_db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# A6 disclosure rule: a qualitative label only, never the raw numeric score
# ---------------------------------------------------------------------------

def test_learner_card_out_has_no_raw_score_field():
    assert "score" not in LearnerCardOut.model_fields
    assert "confidence_score" not in LearnerCardOut.model_fields


def test_learner_card_out_matches_the_exact_frontend_contract():
    assert set(LearnerCardOut.model_fields) == {
        "id", "icon", "title", "captures", "reading", "confidence",
    }


# ---------------------------------------------------------------------------
# confidence_level_from_score: the low/quiet/confident thresholds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, ConfidenceLevel.LOW),
        (0.39, ConfidenceLevel.LOW),
        (0.4, ConfidenceLevel.QUIET),
        (0.69, ConfidenceLevel.QUIET),
        (0.7, ConfidenceLevel.CONFIDENT),
        (1.0, ConfidenceLevel.CONFIDENT),
    ],
)
def test_confidence_level_from_score_thresholds(score, expected):
    assert confidence_level_from_score(score) == expected
