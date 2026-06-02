"""
KR3-19 validators: platform service info (return + delivery) accuracy on filtered offers.
"""

from __future__ import annotations

import re
from typing import Any

from .config import KR3_19_MAX_DELIVERY_DAYS
from .kr3_12_shipping_validator import has_value

FIELD_DELIVERY = "shippingTime"
FIELD_RETURN = "returnPolicy"


def _max_delivery_days(shipping_time: str) -> int | None:
    nums = [int(n) for n in re.findall(r"\d+", str(shipping_time))]
    if not nums:
        return None
    return max(nums)


def _check_offer(offer: dict, max_delivery_days: int) -> tuple[bool, str | None, str | None]:
    """Returns (correct, reason, failed_field)."""
    if not has_value(offer.get(FIELD_RETURN)):
        return False, "field_missing", FIELD_RETURN
    if not has_value(offer.get(FIELD_DELIVERY)):
        return False, "field_missing", FIELD_DELIVERY

    delivery_text = str(offer.get(FIELD_DELIVERY) or "")
    max_days = _max_delivery_days(delivery_text)
    if max_days is not None and max_days > max_delivery_days:
        return False, "delivery_unreasonable", FIELD_DELIVERY

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
        "shippingTime": str(offer.get(FIELD_DELIVERY) or ""),
        "returnPolicy": str(offer.get(FIELD_RETURN) or ""),
        "reason": reason,
        "section": "priceComparison",
    }
    if failed_field:
        issue["failed_field"] = failed_field
    return issue


def validate_platform_service_info(
    offers: list[dict],
    max_delivery_days: int | None = None,
) -> tuple[float | None, list[dict], dict[str, int]]:
    """Returns (accuracy, issues, stats)."""
    limit = KR3_19_MAX_DELIVERY_DAYS if max_delivery_days is None else max_delivery_days

    stats: dict[str, int] = {
        "filtered_total": len(offers) if offers else 0,
        "correct": 0,
        "field_missing": 0,
        "delivery_unreasonable": 0,
    }

    if not offers:
        return None, [], stats

    issues: list[dict] = []
    correct_count = 0

    for i, offer in enumerate(offers):
        ok, reason, failed_field = _check_offer(offer, limit)
        if ok:
            correct_count += 1
        else:
            if reason == "field_missing":
                stats["field_missing"] += 1
            elif reason == "delivery_unreasonable":
                stats["delivery_unreasonable"] += 1
            issues.append(_make_issue(i, offer, reason or "field_missing", failed_field))

    stats["correct"] = correct_count
    accuracy = correct_count / len(offers)
    return accuracy, issues, stats
