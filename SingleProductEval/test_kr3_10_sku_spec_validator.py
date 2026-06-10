"""Tests for KR3-10 SKU spec display (variant_attributes completeness)."""

from __future__ import annotations

from SingleProductEval.kr3_10_sku_spec_validator import validate_sku_spec_display


def _offer(
    *,
    condition_va: str,
    condition_display: str | None = "New",
    retailer: str = "Amazon",
) -> dict:
    offer = {
        "retailer": retailer,
        "variant_attributes": {"Condition": condition_va},
    }
    if condition_display is not None:
        offer["condition"] = condition_display
    return offer


def test_used_offer_correct_despite_default_selection_new():
    report = {"defaultSelection": {"Condition": "New"}}
    offers = [_offer(condition_va="Used", condition_display="Used")]
    accuracy, issues, selection, _ = validate_sku_spec_display(report, offers=offers)
    assert accuracy == 1.0
    assert issues == []
    assert selection == {}


def test_new_offer_with_variant_attributes():
    report = {}
    offers = [_offer(condition_va="New", condition_display="New")]
    accuracy, issues, _, _ = validate_sku_spec_display(report, offers=offers)
    assert accuracy == 1.0
    assert issues == []


def test_passes_without_top_level_condition():
    report = {}
    offers = [{"retailer": "Amazon", "variant_attributes": {"Condition": "New"}}]
    accuracy, issues, _, _ = validate_sku_spec_display(report, offers=offers)
    assert accuracy == 1.0
    assert issues == []


def test_passes_when_top_condition_differs_from_variant():
    report = {}
    offers = [_offer(condition_va="Used", condition_display="New")]
    accuracy, issues, _, _ = validate_sku_spec_display(report, offers=offers)
    assert accuracy == 1.0
    assert issues == []


def test_spec_missing_when_no_variant_attributes():
    report = {}
    offers = [{"retailer": "Amazon", "condition": "New"}]
    accuracy, issues, _, _ = validate_sku_spec_display(report, offers=offers)
    assert accuracy == 0.0
    assert issues[0]["reason"] == "spec_missing"


def test_spec_missing_when_dimension_value_empty():
    report = {}
    offers = [{"retailer": "Amazon", "variant_attributes": {"Condition": ""}}]
    accuracy, issues, _, _ = validate_sku_spec_display(report, offers=offers)
    assert accuracy == 0.0
    assert issues[0]["reason"] == "spec_missing"
    assert issues[0]["failed_dimension"] == "Condition"


def test_mixed_conditions_all_have_variant_attributes():
    report = {"defaultSelection": {"Condition": "New"}}
    offers = [
        _offer(condition_va="New", condition_display="New"),
        _offer(condition_va="Used", condition_display="Used", retailer="eBay"),
        _offer(condition_va="Refurbished", condition_display=None, retailer="Walmart"),
    ]
    accuracy, issues, _, _ = validate_sku_spec_display(report, offers=offers)
    assert accuracy == 1.0
    assert issues == []
