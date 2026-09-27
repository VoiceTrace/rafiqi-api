import httpx

from app.core.config import settings

_TIMEOUT = httpx.Timeout(30.0)


class LLMError(Exception):
    """Raised on any non-2xx response or transport failure from the LLM gateway."""


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
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM gateway request failed: {exc}") from exc

    if response.status_code >= 400:
        raise LLMError(f"LLM gateway returned {response.status_code}: {response.text}")

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected LLM gateway response shape: {data}") from exc
