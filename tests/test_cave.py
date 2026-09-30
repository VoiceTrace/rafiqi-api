"""
Cave chat tests (A2/A3 + safety layer) — no database required.

Tests cover:
- Safety classifier: flags a category, fails open on error/garbage output
- post_message: flagged path skips the chat model and returns a scripted
  reply; clear path calls the chat model normally; either way surfaces
  whatever _maybe_extract produces (or None)
- get_active_conversation: resumes a conversation with a recent message,
  starts fresh (force-extracting the dormant one first) once the most
  recent message is past the 12h active window
- get_owned_conversation: cross-tenant isolation (wrong school_id -> 404)
- _maybe_extract: triggers at the turn-count threshold (or when forced),
  advances its checkpoint only when extraction actually completed
- profile_extraction.extract_and_merge: creates a new trait, merges into an
  existing one via the score-clamp rule, respects message_offset, and
  distinguishes "completed with nothing" ([]) from "failed" (None)
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
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


def _fake_conversation(last_extracted_message_count: int = 0) -> MagicMock:
    convo = MagicMock(spec=Conversation)
    convo.id = uuid.uuid4()
    convo.student_id = uuid.uuid4()
    convo.school_id = uuid.uuid4()
    convo.last_extracted_message_count = last_extracted_message_count
    return convo


def _fake_message(created_at: datetime | None = None) -> MagicMock:
    msg = MagicMock(spec=ConversationMessage)
    msg.created_at = created_at or datetime.now(timezone.utc)
    return msg


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
        patch("app.services.cave._maybe_extract", new=AsyncMock(return_value=None)),
    ):
        reply, updated_traits = await cave_svc.post_message(
            convo, "Ahmed", "some kids are being mean to me", mock_db
        )

    mock_chat.assert_not_awaited()
    assert reply.role == MessageRole.RAFIQI
    assert reply.content == SAFETY_SCRIPTS[SafetyCategory.BULLYING]
    assert updated_traits is None

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
        patch("app.services.cave._maybe_extract", new=AsyncMock(return_value=None)),
    ):
        reply, updated_traits = await cave_svc.post_message(
            convo, "Ahmed", "I like solving puzzles", mock_db
        )

    mock_chat.assert_awaited_once()
    assert reply.content == "Tell me more!"
    assert reply.role == MessageRole.RAFIQI
    assert updated_traits is None


@pytest.mark.asyncio
async def test_post_message_surfaces_extraction_when_it_runs():
    """Most turns don't trigger extraction (None) — when one does, the result
    passes straight through to the caller, whatever it is (including [])."""
    convo = _fake_conversation()
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    sentinel_traits = [MagicMock(spec=ProfileTrait)]

    with (
        patch("app.services.cave.classify_message", new=AsyncMock(return_value=None)),
        patch("app.services.cave._existing_traits", new=AsyncMock(return_value=[])),
        patch("app.services.cave._recent_messages", new=AsyncMock(return_value=[])),
        patch("app.services.cave.chat_completion", new=AsyncMock(return_value="Tell me more!")),
        patch("app.services.cave._maybe_extract", new=AsyncMock(return_value=sentinel_traits)) as mock_extract,
    ):
        _reply, updated_traits = await cave_svc.post_message(convo, "Ahmed", "hi", mock_db)

    mock_extract.assert_awaited_once_with(convo, mock_db)
    assert updated_traits is sentinel_traits


# ---------------------------------------------------------------------------
# get_active_conversation: resume-by-recency, no "ended" state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_conversation_resumes_recent_conversation():
    convo = _fake_conversation()
    recent_message = _fake_message(datetime.now(timezone.utc) - timedelta(hours=2))
    mock_db = AsyncMock()

    with (
        patch("app.services.cave._most_recently_active", new=AsyncMock(return_value=(convo, recent_message))),
        patch("app.services.cave.chat_completion", new=AsyncMock()) as mock_chat,
    ):
        returned_convo, message, is_new = await cave_svc.get_active_conversation(
            convo.student_id, convo.school_id, "Ahmed", mock_db
        )

    mock_chat.assert_not_awaited()  # resuming never makes a fresh LLM call
    assert returned_convo is convo
    assert message is recent_message
    assert is_new is False


@pytest.mark.asyncio
async def test_get_active_conversation_starts_fresh_when_dormant():
    """Most recent conversation's last message is >12h old — starts a new
    conversation, but first force-extracts whatever's unprocessed in the
    dormant one (no /end exists to guarantee that anymore)."""
    dormant = _fake_conversation()
    old_message = _fake_message(datetime.now(timezone.utc) - timedelta(hours=13))
    student_id, school_id = dormant.student_id, dormant.school_id
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    with (
        patch("app.services.cave._most_recently_active", new=AsyncMock(return_value=(dormant, old_message))),
        patch("app.services.cave._maybe_extract", new=AsyncMock(return_value=None)) as mock_extract,
        patch("app.services.cave._existing_traits", new=AsyncMock(return_value=[])),
        patch("app.services.cave.chat_completion", new=AsyncMock(return_value="Hey there!")) as mock_chat,
    ):
        conversation, message, is_new = await cave_svc.get_active_conversation(
            student_id, school_id, "Ahmed", mock_db
        )

    mock_extract.assert_awaited_once_with(dormant, mock_db, force=True)
    mock_chat.assert_awaited_once()
    assert is_new is True
    assert message.content == "Hey there!"
    assert conversation.student_id == student_id
    assert conversation is not dormant  # a genuinely new conversation, not the dormant one


@pytest.mark.asyncio
async def test_get_active_conversation_creates_fresh_when_none_exist():
    student_id, school_id = uuid.uuid4(), uuid.uuid4()
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    with (
        patch("app.services.cave._most_recently_active", new=AsyncMock(return_value=None)),
        patch("app.services.cave._existing_traits", new=AsyncMock(return_value=[])),
        patch("app.services.cave.chat_completion", new=AsyncMock(return_value="Hey there!")) as mock_chat,
    ):
        conversation, message, is_new = await cave_svc.get_active_conversation(
            student_id, school_id, "Ahmed", mock_db
        )

    mock_chat.assert_awaited_once()
    assert is_new is True
    assert message.content == "Hey there!"
    assert conversation.student_id == student_id


# ---------------------------------------------------------------------------
# list_conversations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_conversations_orders_by_recency_and_flags_active():
    convo_old = _fake_conversation()
    convo_new = _fake_conversation()
    old_msg = _fake_message(datetime.now(timezone.utc) - timedelta(hours=20))
    new_msg = _fake_message(datetime.now(timezone.utc) - timedelta(hours=1))

    conversations_result = MagicMock()
    conversations_result.scalars.return_value.all.return_value = [convo_old, convo_new]

    mock_db = AsyncMock()
    mock_db.execute.return_value = conversations_result

    with patch("app.services.cave._last_message", new=AsyncMock(side_effect=[old_msg, new_msg])):
        rows = await cave_svc.list_conversations(convo_old.student_id, convo_old.school_id, mock_db)

    assert [conversation.id for conversation, _, _ in rows] == [convo_new.id, convo_old.id]
    assert rows[0] == (convo_new, new_msg, True)    # most recent + within the active window
    assert rows[1] == (convo_old, old_msg, False)   # older than 12h -> not active, still listed


@pytest.mark.asyncio
async def test_list_conversations_handles_conversation_with_no_messages():
    convo = _fake_conversation()
    conversations_result = MagicMock()
    conversations_result.scalars.return_value.all.return_value = [convo]
    mock_db = AsyncMock()
    mock_db.execute.return_value = conversations_result

    with patch("app.services.cave._last_message", new=AsyncMock(return_value=None)):
        rows = await cave_svc.list_conversations(convo.student_id, convo.school_id, mock_db)

    assert rows == [(convo, None, False)]


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
# _maybe_extract: the 20-turn (or forced) trigger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maybe_extract_does_nothing_below_threshold():
    convo = _fake_conversation(last_extracted_message_count=0)
    mock_db = AsyncMock()

    with (
        patch("app.services.cave._message_count", new=AsyncMock(return_value=19)),
        patch("app.services.cave.profile_extraction.extract_and_merge", new=AsyncMock()) as mock_extract,
    ):
        result = await cave_svc._maybe_extract(convo, mock_db)

    mock_extract.assert_not_awaited()
    assert result is None
    assert convo.last_extracted_message_count == 0  # checkpoint untouched


@pytest.mark.asyncio
async def test_maybe_extract_triggers_at_threshold_and_advances_checkpoint():
    convo = _fake_conversation(last_extracted_message_count=0)
    mock_db = AsyncMock()
    sentinel_traits = [MagicMock(spec=ProfileTrait)]

    with (
        patch("app.services.cave._message_count", new=AsyncMock(return_value=20)),
        patch(
            "app.services.cave.profile_extraction.extract_and_merge",
            new=AsyncMock(return_value=sentinel_traits),
        ) as mock_extract,
    ):
        result = await cave_svc._maybe_extract(convo, mock_db)

    mock_extract.assert_awaited_once_with(convo, mock_db, message_offset=0)
    assert result is sentinel_traits
    assert convo.last_extracted_message_count == 20
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_maybe_extract_force_bypasses_threshold():
    convo = _fake_conversation(last_extracted_message_count=15)
    mock_db = AsyncMock()

    with (
        patch("app.services.cave._message_count", new=AsyncMock(return_value=18)),  # only 3 unprocessed
        patch(
            "app.services.cave.profile_extraction.extract_and_merge",
            new=AsyncMock(return_value=[]),
        ) as mock_extract,
    ):
        result = await cave_svc._maybe_extract(convo, mock_db, force=True)

    mock_extract.assert_awaited_once_with(convo, mock_db, message_offset=15)
    assert result == []
    assert convo.last_extracted_message_count == 18


@pytest.mark.asyncio
async def test_maybe_extract_does_not_advance_checkpoint_on_failure():
    """extract_and_merge returning None means it failed (LLM/parse error) —
    the checkpoint must not advance, so this slice is retried next trigger
    instead of silently skipped forever."""
    convo = _fake_conversation(last_extracted_message_count=0)
    mock_db = AsyncMock()

    with (
        patch("app.services.cave._message_count", new=AsyncMock(return_value=20)),
        patch("app.services.cave.profile_extraction.extract_and_merge", new=AsyncMock(return_value=None)),
    ):
        result = await cave_svc._maybe_extract(convo, mock_db, force=True)

    assert result is None
    assert convo.last_extracted_message_count == 0
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_extract_nothing_unprocessed_is_a_noop():
    convo = _fake_conversation(last_extracted_message_count=20)
    mock_db = AsyncMock()

    with patch("app.services.cave._message_count", new=AsyncMock(return_value=20)):
        result = await cave_svc._maybe_extract(convo, mock_db, force=True)

    assert result is None


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
    assert result == [added_trait]
    mock_db.refresh.assert_awaited_once_with(added_trait)


@pytest.mark.asyncio
async def test_extract_and_merge_respects_message_offset():
    """Only messages after the offset are sent to the model — the checkpoint
    exists precisely so a long conversation doesn't resend/reprocess its
    earlier messages on every pass."""
    convo = _fake_conversation()
    old_message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="OLD MESSAGE — already processed",
    )
    new_message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="NEW MESSAGE — not yet processed",
    )

    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = [old_message, new_message]
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None
    traits_result = MagicMock()
    traits_result.scalars.return_value.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [messages_result, profile_result, traits_result]
    mock_db.add = MagicMock()

    with patch(
        "app.services.profile_extraction.chat_completion",
        new=AsyncMock(return_value=_extraction_response(0.9)),
    ) as mock_chat:
        await profile_extraction.extract_and_merge(convo, mock_db, message_offset=1)

    sent_transcript = mock_chat.call_args.kwargs["messages"][1]["content"]
    assert "NEW MESSAGE" in sent_transcript
    assert "OLD MESSAGE" not in sent_transcript


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

    # A3 promotion rule (v2): model proposes 0.9, but a single pass can only move an
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

    # Transcript was empty once the flagged turn was excluded -> no LLM call, no commit.
    # This is "completed with nothing" ([]), not "failed" (None) — caller should
    # still advance its checkpoint, there's nothing left worth retrying.
    mock_chat.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    assert result == []


@pytest.mark.asyncio
async def test_extract_and_merge_returns_none_on_llm_failure():
    """Distinct from the empty-transcript case: a real failure must be
    signaled differently (None) so the caller knows not to advance its
    checkpoint and to retry this slice later."""
    convo = _fake_conversation()
    message = ConversationMessage(
        id=uuid.uuid4(), school_id=convo.school_id, conversation_id=convo.id,
        role=MessageRole.STUDENT, content="something ordinary",
    )

    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = [message]
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None
    traits_result = MagicMock()
    traits_result.scalars.return_value.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [messages_result, profile_result, traits_result]

    with patch(
        "app.services.profile_extraction.chat_completion",
        new=AsyncMock(side_effect=LLMError("gateway down")),
    ):
        result = await profile_extraction.extract_and_merge(convo, mock_db)

    assert result is None
    mock_db.commit.assert_not_awaited()


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
