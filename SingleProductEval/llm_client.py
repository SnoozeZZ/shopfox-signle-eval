"""
LLM client for Alibaba Cloud Bailian (DashScope OpenAI-compatible API).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from .config import (
    KR3_9_LLM_BASE_URL,
    KR3_9_LLM_MAX_RETRIES,
    KR3_9_LLM_MODEL,
    KR3_9_LLM_RETRY_BACKOFF_SEC,
    KR3_9_LLM_TIMEOUT_SEC,
)
from .env import load_env

load_env()


def has_dashscope_api_key() -> bool:
    return bool(os.getenv("DASHSCOPE_API_KEY", "").strip())


def _extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _is_retryable_error(exc: BaseException) -> bool:
    try:
        from openai import APIConnectionError, APITimeoutError, RateLimitError
    except ImportError:
        return isinstance(exc, (json.JSONDecodeError, ValueError, OSError, TimeoutError))

    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError, json.JSONDecodeError)):
        return True

    status = getattr(exc, "status_code", None)
    if status is not None:
        if status == 429 or status >= 500:
            return True
        if status in (400, 401, 403, 404):
            return False

    exc_name = type(exc).__name__
    if exc_name in ("InternalServerError", "ServiceUnavailableError"):
        return True
    if exc_name in ("AuthenticationError", "BadRequestError", "PermissionDeniedError"):
        return False

    return isinstance(exc, (OSError, TimeoutError, ValueError))


def _call_chat_completion(
    api_key: str,
    system: str,
    user: str,
    model: str,
    enable_thinking: bool,
    timeout_sec: float,
) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=KR3_9_LLM_BASE_URL,
        timeout=timeout_sec,
    )

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        extra_body={"enable_thinking": enable_thinking},
    )
    return completion.choices[0].message.content or ""


def chat_json(
    system: str,
    user: str,
    model: str | None = None,
    enable_thinking: bool = False,
    timeout_sec: float | None = None,
    max_retries: int | None = None,
) -> Any:
    """
    Call Bailian chat completions and parse JSON from the response.
    Retries transient failures with exponential backoff.
    """
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")

    retries = KR3_9_LLM_MAX_RETRIES if max_retries is None else max_retries
    timeout = timeout_sec or KR3_9_LLM_TIMEOUT_SEC
    model_name = model or KR3_9_LLM_MODEL
    last_error: BaseException | None = None

    for attempt in range(retries + 1):
        try:
            content = _call_chat_completion(
                api_key, system, user, model_name, enable_thinking, timeout
            )
            return _extract_json(content)
        except Exception as exc:
            last_error = exc
            if not _is_retryable_error(exc) or attempt >= retries:
                raise
            time.sleep(KR3_9_LLM_RETRY_BACKOFF_SEC * (2**attempt))

    if last_error is not None:
        raise last_error
    raise RuntimeError("chat_json failed without exception")
