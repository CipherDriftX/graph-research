"""LLM client for DeepSeek and Kimi models through OpenRouter.

Both model families go through one OpenAI-compatible endpoint and one key.
The rest of the code uses the short model names below; OPENROUTER_MODEL_SLUGS
maps them to OpenRouter's catalog ids.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from openai import OpenAI
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from src.config import get_config

logger = structlog.get_logger(__name__)

# USD per million tokens, from OpenRouter's GET /api/v1/models (2026-11-23).
# Used when a response does not report its own cost.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {"input": 0.90, "output": 1.50},
    "deepseek-v4-flash": {"input": 0.09, "output": 0.18},
    "kimi-k3": {"input": 0.192, "output": 16.00},
    "kimi-k2.6": {"input": 0.65, "output": 3.41},
}

OPENROUTER_MODEL_SLUGS: dict[str, str] = {
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "kimi-k3": "moonshotai/kimi-k3",
    "kimi-k2.6": "moonshotai/kimi-k2.6",
}

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class EmptyCompletionError(RuntimeError):
    """The provider answered, with nothing in it.

    Seen once on the technology run, where it cost a whole batch of thirty
    video descriptions: the node recorded "empty response" and moved on.
    It is a hiccup rather than a refusal -- the same prompt succeeds on the
    next attempt -- so it belongs with the other retryable conditions
    instead of being charged to the caller.
    """


def _is_retryable(exception: BaseException) -> bool:
    from openai import (
        APIError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    if isinstance(exception, EmptyCompletionError):
        return True
    if isinstance(exception, (RateLimitError, APITimeoutError, InternalServerError)):
        return True
    if isinstance(exception, APIError):
        return getattr(exception, "status_code", None) in RETRYABLE_STATUSES
    return False


#: Retries are bounded by wall clock as well as by count. An attempt count
#: alone assumes attempts are quick, and they are not: a mid-tier crime
#: batch that answers with nothing takes ~2.5 minutes to do it, so five
#: attempts spent twelve minutes on one batch of eight videos and pushed a
#: 30-minute heal budget to 40. Whichever limit is reached first wins.
_MAX_RETRY_SECONDS = 180


def _create_retry_decorator():
    return retry(
        wait=wait_exponential_jitter(initial=1, max=60, jitter=2),
        stop=(stop_after_attempt(5) | stop_after_delay(_MAX_RETRY_SECONDS)),
        retry=retry_if_exception(_is_retryable),
        before_sleep=lambda retry_state: logger.warning(
            "llm_retry",
            attempt=retry_state.attempt_number,
            exc_type=type(retry_state.outcome.exception()).__name__,
            wait_s=retry_state.next_action.sleep if retry_state.next_action else None,
        ),
    )


class LLMClient:
    def __init__(self) -> None:
        self._config = get_config()
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self._config.openrouter.api_key,
                base_url=self._config.openrouter.base_url,
                default_headers={
                    "HTTP-Referer": "https://github.com/CipherDriftX/graph-research",
                    "X-Title": "graph-research",
                },
            )
        return self._client

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str = "deepseek-v4-pro",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        thinking: bool = False,
    ) -> dict[str, Any]:
        client = self._get_client()

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        start = time.monotonic()
        response = self._call_api(client, model, messages, temperature, max_tokens, thinking)
        latency_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        content = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason not in (None, "stop"):
            # "length" means max_tokens cut the reply off; the JSON repair
            # downstream can close the brackets but the lost items are gone.
            logger.warning(
                "llm_completion_incomplete",
                model=model, finish_reason=finish_reason, chars=len(content),
            )
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        reported = getattr(response.usage, "cost", None) if response.usage else None
        cost = (
            float(reported) if isinstance(reported, (int, float))
            else self._calculate_cost(model, prompt_tokens, completion_tokens)
        )

        return {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
            "cost_usd": cost,
            "model": model,
            "latency_ms": latency_ms,
            "finish_reason": finish_reason,
        }

    @_create_retry_decorator()
    def _call_api(
        self,
        client: OpenAI,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        thinking: bool,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": OPENROUTER_MODEL_SLUGS.get(model, model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Ask OpenRouter to report the billed cost with the usage counts.
            "extra_body": {"usage": {"include": True}},
        }
        if thinking and model.startswith("deepseek-v4-pro"):
            kwargs["extra_body"]["thinking"] = {"type": "enabled"}
        response = client.chat.completions.create(**kwargs)
        self._raise_if_blank(response, model)
        return response

    @staticmethod
    def _raise_if_blank(response: Any, model: str) -> None:
        """Reject a completion with nothing in it.

        Called inside the retried request rather than by the caller: every
        prompt this client sends asks for content back, so a blank reply is
        a failed call and earns the same backoff as a 503. A model that
        answers "I cannot help with that" has answered, and is left alone.
        """
        choice = response.choices[0] if response.choices else None
        content = getattr(getattr(choice, "message", None), "content", None) or ""
        if content.strip():
            return
        raise EmptyCompletionError(
            f"{model} returned no content "
            f"(finish_reason={getattr(choice, 'finish_reason', None)})"
        )

    @staticmethod
    def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = MODEL_PRICING.get(model)
        if pricing is None:
            return 0.0
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return round(input_cost + output_cost, 8)


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client