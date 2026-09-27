import json
import logging
import re

import httpx

from app.core.config import settings

_TIMEOUT = httpx.Timeout(30.0)

logger = logging.getLogger(__name__)

# Module-level, reused across calls: a fresh httpx.AsyncClient per request means a
# fresh DNS lookup + TLS handshake every time, no connection pooling — wasteful in
# general, and under concurrent load in this environment observed to make DNS
# resolution itself intermittently fail ("Temporary failure in name resolution")
# purely from lookup volume. One long-lived client is the standard httpx pattern
# for a long-lived async server process.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client


async def aclose() -> None:
    """Closes the shared client's open connections. Call from app shutdown
    (see app/main.py's lifespan) — without this the process holds sockets
    open with no release until it exits."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class LLMError(Exception):
    """Raised on any non-2xx response or transport failure from the LLM gateway."""


async def _post(payload: dict) -> httpx.Response:
    try:
        return await _get_client().post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            json=payload,
        )
    except httpx.HTTPError as exc:
        # str(exc) is empty for several httpx exception types (e.g. ConnectTimeout,
        # RemoteProtocolError) — repr always carries the type, which matters for
        # telling a real outage apart from a transient one at a glance.
        raise LLMError(f"LLM gateway request failed: {exc!r}") from exc


async def chat_completion(
    messages: list[dict],
    model: str,
    *,
    temperature: float = 0.3,
    json_mode: bool = False,
    max_tokens: int = 400,
) -> str:
    """
    Single call to OpenRouter's OpenAI-compatible chat completions endpoint.
    Returns the assistant message content as a string.

    Stateless per call by design (see CLAUDE.md "Personalization mechanism") —
    callers pass whatever context (persona, profile snapshot, history) they
    need as part of `messages`.

    `max_tokens` is always sent explicitly — without it, OpenRouter reserves
    against the model's full default output allowance (tens of thousands of
    tokens) when pricing the request against account balance, which can 402
    even a well-funded account. Every call site here is a short reply or a
    small JSON object, so a low cap is also just correct, not a workaround.

    `json_mode` requests structured output (`response_format: json_object`),
    but not every provider OpenRouter routes a given model to actually
    supports it (observed: 100% failure routing moonshotai/kimi-k2 to
    Novita, "does not support feature: structured-outputs"). Rather than
    hard-failing every JSON call whenever routing lands on such a provider,
    a 400 with `json_mode` retries once with `response_format` dropped —
    callers must parse the result leniently either way (see
    `parse_json_object` below), since without enforced structured output the
    model can still wrap JSON in prose or a code fence despite instructions.
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # moonshotai/kimi-k2 (and other reasoning-capable models) can spend the
        # entire max_tokens budget on internal reasoning before ever writing
        # visible content, returning content=null with finish_reason="length" —
        # observed directly against this gateway. None of our call sites need
        # chain-of-thought, so reasoning is disabled outright rather than just
        # excluded from the response (exclude alone still let it burn tokens).
        "reasoning": {"enabled": False},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = await _post(payload)

    if response.status_code == 400 and json_mode:
        logger.warning(
            "LLM gateway rejected response_format for model=%s, retrying without it: %s",
            model, response.text,
        )
        payload.pop("response_format", None)
        response = await _post(payload)

    if response.status_code >= 400:
        raise LLMError(f"LLM gateway returned {response.status_code}: {response.text}")

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected LLM gateway response shape: {data}") from exc

    if content is None:
        # Observed from upstream providers on sensitive content (e.g. self-harm
        # topics) — treat as a gateway failure rather than propagating None to
        # a caller that will try to persist it into a NOT NULL column.
        raise LLMError(f"LLM gateway returned null content: {data}")

    return content


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """
    Parses a JSON object out of a model response that may not be pure JSON —
    since `json_mode` isn't reliably enforced (see `chat_completion`), the
    model can wrap it in a markdown code fence or add stray text around it.
    Raises json.JSONDecodeError (matching plain json.loads) if nothing usable
    is found, so existing callers' except blocks don't need to change.
    """
    text = text.strip()
    fenced = _CODE_FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise json.JSONDecodeError("No JSON object found in model response", text, 0)
