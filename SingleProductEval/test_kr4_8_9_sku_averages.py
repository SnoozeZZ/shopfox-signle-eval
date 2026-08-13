"""Tests for KR4-8 / KR4-9 SKU-average platform and offer counts."""

from __future__ import annotations

from SingleProductEval.metrics import (
    _sku_spec_combination_count,
    compute_kr4_6_distinct_platform_count,
    compute_kr4_7_unique_offer_count,
    compute_kr4_8_sku_avg_platform_count,
    compute_kr4_9_sku_avg_offer_count,
)


def _report(offers: list[dict], sku_combinations: list[dict] | None = None) -> dict:
    out: dict = {"priceComparison": {"offers": offers}}
    if sku_combinations is not None:
        out["sku_combinations"] = sku_combinations
    return out


def test_combination_count_cartesian_even_if_sku_missing():
    # 2 dims x 2 options each = 4 theoretical combos, only 1 real SKU present
    skus = [
        {"sku_id": "a", "variant_attributes": {"Color": "Black", "Storage": "128GB"}},
        {"sku_id": "b", "variant_attributes": {"Color": "White", "Storage": "256GB"}},
    ]
    assert _sku_spec_combination_count({"sku_combinations": skus}) == 4


def test_kr4_8_9_divide_by_theoretical_n():
    offers = [
        {"retailer": "Amazon", "url": "https://amazon.com/dp/1"},
        {"retailer": "Walmart", "url": "https://walmart.com/ip/1"},
        {"retailer": "Best Buy", "url": "https://bestbuy.com/p/1"},
    ]
    skus = [
        {"sku_id": "only", "variant_attributes": {"Color": "Black", "Storage": "128GB"}},
        {"sku_id": "ghost", "variant_attributes": {"Color": "White", "Storage": "256GB"}},
    ]
    report = _report(offers, skus)
    assert _sku_spec_combination_count(report) == 4
    assert compute_kr4_6_distinct_platform_count(report, {}) == 3
    assert compute_kr4_7_unique_offer_count(report, {}) == 3
    assert compute_kr4_8_sku_avg_platform_count(report, {}) == round(3 / 4, 4)
    assert compute_kr4_9_sku_avg_offer_count(report, {}) == round(3 / 4, 4)


def test_empty_sku_combinations_returns_none():
    report = _report(
        [{"retailer": "Amazon", "url": "https://amazon.com/dp/1"}],
        [],
    )
    assert compute_kr4_8_sku_avg_platform_count(report, {}) is None
    assert compute_kr4_9_sku_avg_offer_count(report, {}) is None


def test_missing_sku_combinations_returns_none():
    report = _report([{"retailer": "Amazon", "url": "https://amazon.com/dp/1"}])
    assert compute_kr4_8_sku_avg_platform_count(report, {}) is None
    assert compute_kr4_9_sku_avg_offer_count(report, {}) is None


def test_option_case_sensitive_dedupe():
    skus = [
        {"variant_attributes": {"Condition": "New"}},
        {"variant_attributes": {"Condition": "new"}},
    ]
    assert _sku_spec_combination_count({"sku_combinations": skus}) == 2


def test_numerator_matches_kr4_6_and_kr4_7():
    offers = [
        {"retailer": "Amazon", "url": "https://amazon.com/dp/B0XXX?tag=a"},
        {"retailer": "Amazon", "url": "https://amazon.com/dp/B0XXX?utm_source=b"},
        {"retailer": "Amazon", "url": "not-a-url"},
        {"retailer": "Walmart", "url": "ftp://files.example/x"},
    ]
    skus = [
        {"variant_attributes": {"Color": "Black"}},
        {"variant_attributes": {"Color": "White"}},
    ]
    report = _report(offers, skus)
    n = 2
    platforms = compute_kr4_6_distinct_platform_count(report, {})
    links = compute_kr4_7_unique_offer_count(report, {})
    # 2 valid (tracking differs) + 2 invalid = 4; Amazon + Walmart = 2 platforms
    assert links == 4
    assert platforms == 2
    assert compute_kr4_8_sku_avg_platform_count(report, {}) == round(platforms / n, 4)
    assert compute_kr4_9_sku_avg_offer_count(report, {}) == round(links / n, 4)


def test_empty_option_value_skipped():
    skus = [
        {"variant_attributes": {"Color": "Black", "Storage": ""}},
        {"variant_attributes": {"Color": "White", "Storage": "   "}},
    ]
    # Storage has no non-empty options → only Color contributes → N=2
    assert _sku_spec_combination_count({"sku_combinations": skus}) == 2
