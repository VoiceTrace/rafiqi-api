"""
Cave chat tests (A2/A3 + safety layer) — no database required.

Tests cover:
- Safety classifier: flags a category, fails open on error/garbage output
- post_message: flagged path skips the chat model and returns a scripted
  reply; clear path calls the chat model normally
- post_message: rejects sending into an already-ended conversation
- get_owned_conversation: cross-tenant isolation (wrong school_id -> 404)
- end_conversation: rejects ending twice, otherwise runs extraction
- profile_extraction.extract_and_merge: creates a new trait, and merges into
  an existing one via the weighted-average promotion rule
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.conversation import Conversation
from app.models.message import ConversationMessage, MessageRole, SafetyCategory
from app.models.profile import ConfidenceLabel, ProfileTrait
from app.schemas.profile import CONFIDENCE_THRESHOLD, TraitCategory, TraitKey
from app.services import cave as cave_svc
from app.services import profile_extraction
from app.services.llm import LLMError
from app.services.safety import SAFETY_SCRIPTS, classify_message


def _fake_conversation(ended_at=None) -> MagicMock:
    convo = MagicMock(spec=Conversation)
    convo.id = uuid.uuid4()
    convo.student_id = uuid.uuid4()
    convo.school_id = uuid.uuid4()
    convo.ended_at = ended_at
    return convo


# ---------------------------------------------------------------------------
# Safety classifier
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_message_returns_category():
    with patch(
        "app.services.safety.chat_completion",
        new=AsyncMock(return_value=json.dumps({"category": "self_harm"})),
    ):
        result = await classify_message("I don't want to be here anymore")
    assert result == SafetyCategory.SELF_HARM


@pytest.mark.asyncio
async def test_classify_message_returns_none_when_clear():
    with patch(
        "app.services.safety.chat_completion",
        new=AsyncMock(return_value=json.dumps({"category": None})),
    ):
        result = await classify_message("Math is hard but I like a challenge")
    assert result is None


@pytest.mark.asyncio
async def test_classify_message_fails_open_on_llm_error():
    with patch(
        "app.services.safety.chat_completion",
        new=AsyncMock(side_effect=LLMError("gateway down")),
    ):
        result = await classify_message("anything")
    assert result is None


@pytest.mark.asyncio
async def test_classify_message_fails_open_on_garbage_json():
    with patch(
        "app.services.safety.chat_completion",
        new=AsyncMock(return_value="not json at all"),
    ):
        result = await classify_message("anything")
    assert result is None


@pytest.mark.asyncio
async def test_classify_message_fails_open_on_unknown_category():
    with patch(
        "app.services.safety.chat_completion",
        new=AsyncMock(return_value=json.dumps({"category": "made_up_category"})),
    ):
        result = await classify_message("anything")
    assert result is None


def test_every_safety_category_has_a_scripted_reply():
    """Deterministic-reply guarantee: no category can fall through to a model reply."""
    for category in SafetyCategory:
        assert category in SAFETY_SCRIPTS
        assert SAFETY_SCRIPTS[category]


# ---------------------------------------------------------------------------
# post_message: flagged path skips the chat model entirely
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_message_flagged_skips_chat_model_and_returns_script():
    convo = _fake_conversation()
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    with (
        patch("app.services.cave.classify_message", new=AsyncMock(return_value=SafetyCategory.BULLYING)),
        patch("app.services.cave.chat_completion", new=AsyncMock()) as mock_chat,
    ):
        reply = await cave_svc.post_message(convo, "Ahmed", "some kids are being mean to me", mock_db)

    mock_chat.assert_not_awaited()
    assert reply.role == MessageRole.RAFIQI
    assert reply.content == SAFETY_SCRIPTS[SafetyCategory.BULLYING]

    student_message = mock_db.add.call_args_list[0].args[0]
    assert student_message.flagged is True
    assert student_message.flag_category == SafetyCategory.BULLYING.value


@pytest.mark.asyncio
async def test_post_message_clear_calls_chat_model():
    convo = _fake_conversation()
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    with (
        patch("app.services.cave.classify_message", new=AsyncMock(return_value=None)),
        patch("app.services.cave._existing_traits", new=AsyncMock(return_value=[])),
        patch("app.services.cave._recent_messages", new=AsyncMock(return_value=[])),
        patch("app.services.cave.chat_completion", new=AsyncMock(return_value="Tell me more!")) as mock_chat,
    ):
        reply = await cave_svc.post_message(convo, "Ahmed", "I like solving puzzles", mock_db)

    mock_chat.assert_awaited_once()
    assert reply.content == "Tell me more!"
    assert reply.role == MessageRole.RAFIQI


@pytest.mark.asyncio
async def test_post_message_rejects_ended_conversation():
    convo = _fake_conversation(ended_at=datetime.now(timezone.utc))
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await cave_svc.post_message(convo, "Ahmed", "hello?", mock_db)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_owned_conversation: cross-tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_owned_conversation_wrong_school_raises_404():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # school_id filter excluded the row
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await cave_svc.get_owned_conversation(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), mock_db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# end_conversation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_conversation_sets_ended_at_and_runs_extraction():
    convo = _fake_conversation()
    mock_db = AsyncMock()
    sentinel_traits = [MagicMock()]

    with patch(
        "app.services.cave.profile_extraction.extract_and_merge",
        new=AsyncMock(return_value=sentinel_traits),
    ) as mock_extract:
        result = await cave_svc.end_conversation(convo, mock_db)

    assert convo.ended_at is not None
    mock_extract.assert_awaited_once_with(convo, mock_db)
    assert result is sentinel_traits


@pytest.mark.asyncio
async def test_end_conversation_rejects_double_end():
    convo = _fake_conversation(ended_at=datetime.now(timezone.utc))
    mock_db = AsyncMock()

    with patch("app.services.cave.profile_extraction.extract_and_merge", new=AsyncMock()) as mock_extract:
        with pytest.raises(HTTPException) as exc_info:
            await cave_svc.end_conversation(convo, mock_db)

    assert exc_info.value.status_code == 400
    mock_extract.assert_not_awaited()


# ---------------------------------------------------------------------------
# A3 — profile_extraction.extract_and_merge
# ---------------------------------------------------------------------------

_TRAIT_KEY = TraitKey.CURIOUS.value
_CATEGORY = TraitCategory.PREFERENCES.value


def _extraction_response(observed_score: float) -> str:
    return json.dumps(
        {
            "observations": [
                {
                    "trait_key": _TRAIT_KEY,
                    "category": _CATEGORY,
                    "observed_score": observed_score,
                    "title": "Curious",
                    "description": "Asks a lot of follow-up questions.",
                    "teaching_tip": "Give them room to go off on tangents.",
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_extract_and_merge_creates_new_trait_when_none_exists():
    convo = _fake_conversation()
    message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="I always wonder why things work the way they do",
    )

    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = [message]
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None  # no existing profile
    traits_result = MagicMock()
    traits_result.scalars.return_value.all.return_value = []  # no existing traits

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [messages_result, profile_result, traits_result]
    mock_db.add = MagicMock()

    with patch(
        "app.services.profile_extraction.chat_completion",
        new=AsyncMock(return_value=_extraction_response(0.9)),
    ):
        result = await profile_extraction.extract_and_merge(convo, mock_db)

    added_trait = next(
        call.args[0] for call in mock_db.add.call_args_list if isinstance(call.args[0], ProfileTrait)
    )
    assert added_trait.trait_key == _TRAIT_KEY
    assert added_trait.score == 0.9
    assert added_trait.confidence == ConfidenceLabel.CONFIDENT
    assert added_trait.source_conversation_id == convo.id
    mock_db.commit.assert_awaited()
    # Returned so the caller (end_conversation route) can show "what Rafiqi learned"
    assert result == [added_trait]
    mock_db.refresh.assert_awaited_once_with(added_trait)


@pytest.mark.asyncio
async def test_extract_and_merge_clamps_score_movement_for_existing_trait():
    convo = _fake_conversation()
    message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="I always wonder why things work the way they do",
    )
    existing_trait = ProfileTrait(
        id=uuid.uuid4(),
        school_id=convo.school_id,
        profile_id=uuid.uuid4(),
        category=_CATEGORY,
        trait_key=_TRAIT_KEY,
        title="Curious",
        description="Old description",
        score=0.5,
        confidence=ConfidenceLabel.STILL_FORMING,
    )
    fake_profile = MagicMock()
    fake_profile.id = existing_trait.profile_id

    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = [message]
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = fake_profile
    traits_result = MagicMock()
    traits_result.scalars.return_value.all.return_value = [existing_trait]

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [messages_result, profile_result, traits_result]
    mock_db.add = MagicMock()

    with patch(
        "app.services.profile_extraction.chat_completion",
        new=AsyncMock(return_value=_extraction_response(0.9)),
    ):
        result = await profile_extraction.extract_and_merge(convo, mock_db)

    # A3 promotion rule (v2): model proposes 0.9, but a single session can only move an
    # existing score by up to 0.3 -> 0.5 + 0.3 = 0.8, not straight to the model's 0.9.
    assert existing_trait.score == pytest.approx(0.8)
    assert existing_trait.confidence == ConfidenceLabel.CONFIDENT  # 0.8 crosses the 0.7 threshold
    assert existing_trait.source_conversation_id == convo.id
    mock_db.commit.assert_awaited()
    assert result == [existing_trait]


@pytest.mark.asyncio
async def test_extract_and_merge_clamps_downward_movement_too():
    convo = _fake_conversation()
    message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="Actually I hate figuring things out myself",
    )
    existing_trait = ProfileTrait(
        id=uuid.uuid4(),
        school_id=convo.school_id,
        profile_id=uuid.uuid4(),
        category=_CATEGORY,
        trait_key=_TRAIT_KEY,
        title="Curious",
        description="Old description",
        score=0.9,
        confidence=ConfidenceLabel.CONFIDENT,
    )
    fake_profile = MagicMock()
    fake_profile.id = existing_trait.profile_id

    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = [message]
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = fake_profile
    traits_result = MagicMock()
    traits_result.scalars.return_value.all.return_value = [existing_trait]

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [messages_result, profile_result, traits_result]
    mock_db.add = MagicMock()

    with patch(
        "app.services.profile_extraction.chat_completion",
        new=AsyncMock(return_value=_extraction_response(0.1)),
    ):
        result = await profile_extraction.extract_and_merge(convo, mock_db)

    # Model proposes 0.1, clamp limits the drop to -0.3 -> 0.9 - 0.3 = 0.6, not straight to 0.1.
    assert existing_trait.score == pytest.approx(0.6)
    assert result == [existing_trait]


@pytest.mark.asyncio
async def test_extract_and_merge_excludes_flagged_messages_from_transcript():
    convo = _fake_conversation()
    flagged_message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="something in crisis", flagged=True,
        flag_category=SafetyCategory.SELF_HARM.value,
    )

    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = [flagged_message]

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [messages_result]

    with patch("app.services.profile_extraction.chat_completion", new=AsyncMock()) as mock_chat:
        result = await profile_extraction.extract_and_merge(convo, mock_db)

    # Transcript was empty once the flagged turn was excluded -> no LLM call, no commit
    mock_chat.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    assert result == []


@pytest.mark.asyncio
async def test_extract_and_merge_skips_no_op_description():
    """
    Deterministic backstop: even though the prompt says to leave a trait out
    entirely when nothing changed, the model has been observed to include it
    anyway with a description that just narrates "no new signal" — which
    would otherwise overwrite a real description with junk.
    """
    convo = _fake_conversation()
    message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="something unrelated",
    )
    existing_trait = ProfileTrait(
        id=uuid.uuid4(),
        school_id=convo.school_id,
        profile_id=uuid.uuid4(),
        category=_CATEGORY,
        trait_key=_TRAIT_KEY,
        title="Curious",
        description="Asks a lot of follow-up questions.",
        score=0.8,
        confidence=ConfidenceLabel.CONFIDENT,
    )
    fake_profile = MagicMock()
    fake_profile.id = existing_trait.profile_id

    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = [message]
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = fake_profile
    traits_result = MagicMock()
    traits_result.scalars.return_value.all.return_value = [existing_trait]

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [messages_result, profile_result, traits_result]
    mock_db.add = MagicMock()

    no_op_response = json.dumps(
        {
            "observations": [
                {
                    "trait_key": _TRAIT_KEY,
                    "category": _CATEGORY,
                    "observed_score": 0.8,
                    "title": "Curious",
                    "description": "No new signal in this conversation; remains unchanged.",
                    "teaching_tip": None,
                }
            ]
        }
    )

    with patch(
        "app.services.profile_extraction.chat_completion",
        new=AsyncMock(return_value=no_op_response),
    ):
        result = await profile_extraction.extract_and_merge(convo, mock_db)

    # The original description survives untouched, and nothing is reported as updated
    assert existing_trait.description == "Asks a lot of follow-up questions."
    assert result == []


def test_confidence_threshold_unchanged():
    """Guards against silently changing the shared A1 threshold from this ticket."""
    assert CONFIDENCE_THRESHOLD == 0.7
