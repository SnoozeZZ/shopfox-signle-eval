"""
KR3-10 validators: variant_attributes completeness on all offers.
"""

from __future__ import annotations

from typing import Any


def _check_offer_self_consistency(offer: dict) -> tuple[bool, str | None, str | None]:
    """
    Returns (correct, reason, failed_dimension).
    Checks variant_attributes exists and each dimension has a non-empty value.
    """
    va = offer.get("variant_attributes")
    if not isinstance(va, dict) or not va:
        return False, "spec_missing", ""

    for dim, expected in va.items():
        if not str(expected or "").strip():
            return False, "spec_missing", dim

    return True, None, None


def _offer_specs_from_va(offer: dict) -> dict[str, Any]:
    va = offer.get("variant_attributes")
    if not isinstance(va, dict):
        return {}
    return dict(va)


def _make_issue(
    index: int,
    offer: dict,
    reason: str,
    failed_dimension: str,
) -> dict:
    offer_specs = _offer_specs_from_va(offer)
    issue: dict[str, Any] = {
        "index": index,
        "retailer": str(offer.get("retailer") or ""),
        "offer_specs": offer_specs,
        "reason": reason,
        "failed_dimension": failed_dimension,
        "section": "priceComparison",
    }
    top_condition = offer.get("condition")
    if top_condition is not None and str(top_condition).strip():
        issue["display_condition"] = str(top_condition)
    return issue


def validate_sku_spec_display(
    report: dict,
    offers: list[dict] | None = None,
) -> tuple[float | None, list[dict], dict[str, str], list[str]]:
    """
    Returns (accuracy, issues, empty_selection_placeholder, warnings).

    Third tuple element is kept for API compatibility; always {} (defaultSelection ignored).
    """
    del report
    warnings: list[str] = []

    if not offers:
        return None, [], {}, warnings

    issues: list[dict] = []
    correct_count = 0

    for i, offer in enumerate(offers):
        correct, reason, failed_dim = _check_offer_self_consistency(offer)
        if correct:
            correct_count += 1
        else:
            issues.append(
                _make_issue(
                    i,
                    offer,
                    reason or "spec_missing",
                    failed_dim or "",
                )
            )

    accuracy = correct_count / len(offers)
    return accuracy, issues, {}, warnings
