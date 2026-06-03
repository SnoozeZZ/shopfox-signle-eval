"""
POST evaluation results to the backend callback URL.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .env import load_env

load_env()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _callback_enabled() -> bool:
    return _env_bool("EVAL_CALLBACK_ENABLED", False)


def _callback_url() -> str:
    return os.getenv("EVAL_CALLBACK_URL", "").strip()


def _callback_timeout() -> float:
    try:
        return float(os.getenv("EVAL_CALLBACK_TIMEOUT_SEC", "30"))
    except ValueError:
        return 30.0


def build_callback_payload(
    *,
    success: bool,
    report_id: str,
    run_id: str,
    search_term: str,
    status: str,
    completed_at: str,
    metrics: dict[str, Any],
    error: str | None,
) -> dict[str, Any]:
    """JSON body keys aligned with backend Java DTO (camelCase)."""
    return {
        "success": success,
        "reportId": report_id,
        "runId": run_id,
        "searchTerm": search_term,
        "status": status,
        "completedAt": completed_at,
        "metrics": metrics,
        "error": error,
    }


def notify_backend(payload: dict[str, Any]) -> dict[str, Any]:
    """
    POST payload to EVAL_CALLBACK_URL when enabled.
    Returns metadata: skipped, ok, status_code, error.
    """
    if not _callback_enabled():
        return {"skipped": True, "reason": "EVAL_CALLBACK_ENABLED is false"}

    url = _callback_url()
    if not url:
        return {"skipped": True, "reason": "EVAL_CALLBACK_URL is empty"}

    timeout = _callback_timeout()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
        return {
            "skipped": False,
            "ok": resp.is_success,
            "status_code": resp.status_code,
            "error": None if resp.is_success else resp.text[:500],
        }
    except Exception as exc:
        return {
            "skipped": False,
            "ok": False,
            "status_code": None,
            "error": str(exc),
        }
