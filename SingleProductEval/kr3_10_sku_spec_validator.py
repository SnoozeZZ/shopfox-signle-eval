"""
KR3-10 validators: SKU spec display accuracy on filtered offers.
"""

from __future__ import annotations

from typing import Any


def _values_match(dim: str, expected: str, actual: str) -> bool:
    from .metrics import _normalize_condition, _normalize_variant_value

    if dim.lower() == "condition":
        return _normalize_condition(expected) == _normalize_condition(actual)
    return _normalize_variant_value(expected) == _normalize_variant_value(actual)


def _check_offer_specs(
    offer: dict,
    user_selection: dict[str, str],
) -> tuple[bool, str | None, str | None]:
    """
    Returns (correct, reason, failed_dimension).
    """
    from .metrics import _fuzzy_key_match

    va = offer.get("variant_attributes")
    if not isinstance(va, dict):
        va = {}

    offer_specs: dict[str, Any] = {}

    for dim, expected in user_selection.items():
        matched_key = _fuzzy_key_match(dim, va)
        if matched_key is None:
            return False, "spec_missing", dim

        actual_va = str(va[matched_key])
        offer_specs[dim] = actual_va

        if not _values_match(dim, expected, actual_va):
            return False, "spec_value_mismatch", dim

        if dim.lower() == "condition":
            top_condition = str(offer.get("condition") or "").strip()
            if not top_condition:
                return False, "display_field_missing", dim
            if not _values_match(dim, expected, top_condition):
                if _values_match(dim, actual_va, top_condition):
                    return False, "display_inconsistent", dim
                return False, "spec_value_mismatch", dim

    return True, None, None


def _make_issue(
    index: int,
    offer: dict,
    user_selection: dict[str, str],
    reason: str,
    failed_dimension: str,
) -> dict:
    va = offer.get("variant_attributes") if isinstance(offer.get("variant_attributes"), dict) else {}
    offer_specs = {}
    for dim in user_selection:
        from .metrics import _fuzzy_key_match

        key = _fuzzy_key_match(dim, va)
        if key is not None:
            offer_specs[dim] = va[key]

    issue: dict[str, Any] = {
        "index": index,
        "retailer": str(offer.get("retailer") or ""),
        "user_selection": dict(user_selection),
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
    Returns (accuracy, issues, user_selection, warnings).
    """
    from .metrics import _derive_default_selection

    warnings: list[str] = []
    user_selection = _derive_default_selection(report)

    if not offers:
        return None, [], user_selection, warnings

    if not user_selection:
        warnings.append("kr3_10: no user selection derived")
        return None, [], user_selection, warnings

    issues: list[dict] = []
    correct_count = 0

    for i, offer in enumerate(offers):
        correct, reason, failed_dim = _check_offer_specs(offer, user_selection)
        if correct:
            correct_count += 1
        else:
            issues.append(
                _make_issue(
                    i,
                    offer,
                    user_selection,
                    reason or "spec_value_mismatch",
                    failed_dim or "",
                )
            )

    accuracy = correct_count / len(offers)
    return accuracy, issues, user_selection, warnings
