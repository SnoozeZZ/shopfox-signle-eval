"""
POST evaluation results to the backend external-callback URL.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .env import load_env
from .eval_callback_transform import build_external_callback_payload

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


def _parse_callback_response(resp: httpx.Response) -> tuple[bool, str | None]:
    if not resp.is_success:
        return False, f"HTTP {resp.status_code}: {resp.text[:500]}"
    try:
        body = resp.json()
    except Exception:
        return False, f"HTTP {resp.status_code}: non-JSON response"
    if not isinstance(body, dict):
        return False, f"HTTP {resp.status_code}: unexpected response type"
    code = body.get("code")
    if code != 0:
        message = body.get("message", "")
        return False, f"callback code={code} message={message}"
    return True, None


def notify_backend(payload: dict[str, Any]) -> dict[str, Any]:
    """
    POST payload to EVAL_CALLBACK_URL when enabled.
    Returns metadata: skipped, ok, status_code, error, response_body.
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
        ok, err = _parse_callback_response(resp)
        response_body: Any = None
        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text[:500]
        return {
            "skipped": False,
            "ok": ok,
            "status_code": resp.status_code,
            "error": err,
            "response_body": response_body,
        }
    except Exception as exc:
        return {
            "skipped": False,
            "ok": False,
            "status_code": None,
            "error": str(exc),
        }


def notify_external_callback(
    *,
    run_id: str,
    report_id: str,
    search_term: str,
    raw_metrics: dict[str, Any],
    enabled_metrics: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build external-callback payload and POST to backend."""
    payload = build_external_callback_payload(
        run_id=run_id,
        report_id=report_id,
        search_term=search_term,
        raw_metrics=raw_metrics,
        enabled_metrics=enabled_metrics,
    )
    meta = notify_backend(payload)
    return payload, meta
