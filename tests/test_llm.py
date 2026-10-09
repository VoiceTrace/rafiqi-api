"""
LLM gateway tests — no network required (chat_completion's HTTP call is
mocked at `_post`; `_strip_think_tags` is tested directly as pure logic).

Tests cover:
- _strip_think_tags: removes a closed <think>...</think> block, handles an
  unclosed one (truncated mid-reasoning), case-insensitive, leaves normal
  content untouched
- chat_completion: strips a leaked <think> block from a real response before
  returning it; raises LLMError rather than returning empty content when a
  response is nothing but an (unclosed) reasoning block
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm import LLMError, _strip_think_tags, chat_completion


def test_strip_think_tags_removes_closed_block():
    raw = "<think>reasoning about the student...</think>\n\nHere's the actual reply."
    assert _strip_think_tags(raw) == "Here's the actual reply."


def test_strip_think_tags_is_case_insensitive():
    raw = "<THINK>stuff</THINK>Reply here."
    assert _strip_think_tags(raw) == "Reply here."


def test_strip_think_tags_handles_unclosed_tag():
    """Likely cause: reasoning truncated mid-sentence by max_tokens, no
    closing tag ever written — strip from the tag to the end rather than
    leave raw reasoning text as the "reply"."""
    raw = "<think>reasoning that got cut off mid-sentence because of max_tokens"
    assert _strip_think_tags(raw) == ""


def test_strip_think_tags_leaves_normal_content_untouched():
    raw = "Just a normal reply, no tags at all."
    assert _strip_think_tags(raw) == raw


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


@pytest.mark.asyncio
async def test_chat_completion_strips_leaked_think_block():
    """Observed live: a real Cave reply shown to a student had a raw
    <think>...</think> chain-of-thought block prepended to the actual
    message, despite reasoning.enabled=false in the request."""
    response = _fake_response("<think>internal reasoning here</think>\n\nThe real reply.")

    with patch("app.services.llm._post", new=AsyncMock(return_value=response)):
        result = await chat_completion(messages=[{"role": "user", "content": "hi"}], model="test-model")

    assert result == "The real reply."


@pytest.mark.asyncio
async def test_chat_completion_content_without_think_tag_is_untouched():
    response = _fake_response("A perfectly normal reply.")

    with patch("app.services.llm._post", new=AsyncMock(return_value=response)):
        result = await chat_completion(messages=[{"role": "user", "content": "hi"}], model="test-model")

    assert result == "A perfectly normal reply."


@pytest.mark.asyncio
async def test_chat_completion_raises_when_only_reasoning_returned():
    """An unclosed <think> block with nothing after it (truncated by
    max_tokens) would otherwise return an empty string as if it were a
    valid reply — must fail instead, same as null content, so the caller's
    existing error handling (502, no DB write of empty content) applies."""
    response = _fake_response("<think>only reasoning, nothing else, got cut off")

    with patch("app.services.llm._post", new=AsyncMock(return_value=response)):
        with pytest.raises(LLMError):
            await chat_completion(messages=[{"role": "user", "content": "hi"}], model="test-model")
