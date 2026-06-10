"""
KR3-12 validators: shipping cost accuracy on all offers.
"""

from __future__ import annotations

from typing import Any

_INVALID_VALUES = frozenset({"", "n/a", "na", "none", "null", "-"})

FIELD_SHIPPING = "shippingCost"


def has_value(text: Any) -> bool:
    """Non-empty and not in the invalid placeholder set."""
    return str(text or "").strip().lower() not in _INVALID_VALUES


def _check_offer(offer: dict) -> tuple[bool, str | None, str | None]:
    """Returns (correct, reason, failed_field)."""
    if not has_value(offer.get(FIELD_SHIPPING)):
        return False, "field_missing", FIELD_SHIPPING
    return True, None, None


def _make_issue(
    index: int,
    offer: dict,
    reason: str,
    failed_field: str | None,
) -> dict:
    issue: dict[str, Any] = {
        "index": index,
        "retailer": str(offer.get("retailer") or ""),
        "shippingCost": str(offer.get(FIELD_SHIPPING) or ""),
        "reason": reason,
        "section": "priceComparison",
    }
    if failed_field:
        issue["failed_field"] = failed_field
    return issue


def validate_shipping_info(
    offers: list[dict],
) -> tuple[float | None, list[dict], dict[str, int]]:
    """Returns (accuracy, issues, stats)."""
    stats: dict[str, int] = {
        "filtered_total": len(offers) if offers else 0,
        "correct": 0,
        "field_missing": 0,
    }

    if not offers:
        return None, [], stats

    issues: list[dict] = []
    correct_count = 0

    for i, offer in enumerate(offers):
        ok, reason, failed_field = _check_offer(offer)
        if ok:
            correct_count += 1
        else:
            stats["field_missing"] += 1
            issues.append(_make_issue(i, offer, reason or "field_missing", failed_field))

    stats["correct"] = correct_count
    accuracy = correct_count / len(offers)
    return accuracy, issues, stats
