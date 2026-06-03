"""
Transform raw_metrics into backend external-callback payload.

POST /v1/eval/runs/external-callback
krId and attributionKr use METRICS_REGISTRY metric id (e.g. spu_model_accuracy).
"""

from __future__ import annotations

from typing import Any

from .config import (
    CALLBACK_ISSUE_SOURCE_MAP,
    CALLBACK_ISSUES_MAX,
    CALLBACK_SKIP_METRIC_IDS,
    DEFAULT_ENABLED_METRICS,
    METRICS_REGISTRY,
)

_METRIC_TYPE_BY_ID: dict[str, str] = {m["id"]: m["type"] for m in METRICS_REGISTRY}


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _metric_result(metric_id: str, value: Any) -> dict[str, Any]:
    return {
        "krId": metric_id,
        "value": _format_value(value),
        "valueType": _METRIC_TYPE_BY_ID.get(metric_id, "string"),
        "passed": value is not None,
        "reason": "",
    }


def _build_metrics_array(
    raw_metrics: dict[str, Any],
    enabled_metrics: list[str] | None,
) -> list[dict[str, Any]]:
    enabled = enabled_metrics or list(DEFAULT_ENABLED_METRICS)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for metric_id in enabled:
        if metric_id in CALLBACK_SKIP_METRIC_IDS:
            continue
        if metric_id in seen:
            continue
        if metric_id not in raw_metrics and metric_id not in _METRIC_TYPE_BY_ID:
            continue
        seen.add(metric_id)
        value = raw_metrics.get(metric_id)
        results.append(_metric_result(metric_id, value))

    for key, value in raw_metrics.items():
        if key.startswith("_") or key in seen or key in CALLBACK_SKIP_METRIC_IDS:
            continue
        if key not in _METRIC_TYPE_BY_ID:
            continue
        seen.add(key)
        results.append(_metric_result(key, value))

    return results


def _describe_dict_issue(issue: dict[str, Any]) -> str:
    parts: list[str] = []
    for label, field in (
        ("retailer", "retailer"),
        ("reason", "reason"),
        ("model", "offer_model"),
        ("product_model", "product_model"),
        ("name", "product_name"),
        ("detail", "detail"),
    ):
        val = issue.get(field)
        if val:
            parts.append(f"{label}={val}")
    text = "; ".join(parts) if parts else str(issue)
    return text[:500]


def _issue_entry(
    attribution_kr: str,
    description: str,
    *,
    priority: str = "P1",
    section: str = "",
    link: str = "",
) -> dict[str, str]:
    return {
        "attributionKr": attribution_kr,
        "description": description[:500],
        "priority": priority,
        "section": section,
        "link": link,
    }


def _collect_issues(raw_metrics: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    if raw_metrics.get("_error"):
        issues.append(
            _issue_entry(
                "eval",
                f"eval_error: {raw_metrics['_error']}",
                priority="P0",
            )
        )

    if raw_metrics.get("report_success") == "fail":
        issues.append(
            _issue_entry(
                "report_success",
                "report_success is fail",
                priority="P0",
            )
        )

    for raw_key, attribution_kr in CALLBACK_ISSUE_SOURCE_MAP.items():
        items = raw_metrics.get(raw_key)
        if not items:
            continue
        if raw_key == "_kr3_1_issues":
            for item in items:
                if isinstance(item, str) and item.strip():
                    issues.append(
                        _issue_entry(attribution_kr, item.strip(), section="spec")
                    )
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            issues.append(
                _issue_entry(
                    attribution_kr,
                    _describe_dict_issue(item),
                    section=str(item.get("section") or "priceComparison"),
                    link=str(item.get("url") or ""),
                )
            )

    warnings = raw_metrics.get("_warnings") or []
    if isinstance(warnings, list):
        for w in warnings:
            if w and str(w).strip():
                issues.append(
                    _issue_entry("eval", str(w).strip(), priority="P2")
                )

    return issues[:CALLBACK_ISSUES_MAX]


def build_external_callback_payload(
    *,
    run_id: str,
    report_id: str,
    search_term: str,
    raw_metrics: dict[str, Any],
    enabled_metrics: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "runId": run_id,
        "reportId": report_id,
        "searchTerm": search_term,
        "metrics": _build_metrics_array(raw_metrics, enabled_metrics),
        "issues": _collect_issues(raw_metrics),
    }
