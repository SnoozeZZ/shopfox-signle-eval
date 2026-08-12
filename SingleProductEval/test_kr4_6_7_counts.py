"""Tests for KR4-6 distinct platforms and KR4-7 unique offer URL counts."""

from __future__ import annotations

from SingleProductEval.metrics import (
    compute_kr4_6_distinct_platform_count,
    compute_kr4_7_unique_offer_count,
)


def _report(offers: list[dict]) -> dict:
    return {"priceComparison": {"offers": offers}}


def test_kr4_6_same_platform_dedupes():
    report = _report(
        [
            {"retailer": "Amazon", "url": "https://amazon.com/dp/1"},
            {"retailer": "Amazon", "url": "https://amazon.com/dp/2"},
            {"retailer": "amazon.com", "url": "https://amazon.com/dp/3"},
        ]
    )
    assert compute_kr4_6_distinct_platform_count(report, {}) == 1


def test_kr4_6_multiple_platforms():
    report = _report(
        [
            {"retailer": "Amazon", "url": "https://amazon.com/dp/1"},
            {"retailer": "Walmart", "url": "https://walmart.com/ip/1"},
            {"retailer": "Best Buy", "url": "https://bestbuy.com/product/1"},
        ]
    )
    assert compute_kr4_6_distinct_platform_count(report, {}) == 3


def test_kr4_7_same_valid_url_dedupes():
    u = "https://www.amazon.com/dp/B0XXX"
    report = _report(
        [
            {"retailer": "Amazon", "url": u},
            {"retailer": "Amazon", "url": u},
        ]
    )
    assert compute_kr4_7_unique_offer_count(report, {}) == 1


def test_kr4_7_tracking_difference_counts_as_two():
    report = _report(
        [
            {"retailer": "Amazon", "url": "https://amazon.com/dp/B0XXX?tag=a"},
            {"retailer": "Amazon", "url": "https://amazon.com/dp/B0XXX?utm_source=b"},
        ]
    )
    assert compute_kr4_7_unique_offer_count(report, {}) == 2


def test_kr4_7_empty_url_excluded():
    report = _report(
        [
            {"retailer": "Amazon", "url": ""},
            {"retailer": "Amazon", "url": "   "},
            {"retailer": "Amazon", "url": "https://amazon.com/dp/1"},
        ]
    )
    assert compute_kr4_7_unique_offer_count(report, {}) == 1


def test_kr4_7_invalid_urls_each_count_one():
    report = _report(
        [
            {"retailer": "Amazon", "url": "not-a-url"},
            {"retailer": "Amazon", "url": "not-a-url"},
            {"retailer": "Amazon", "url": "ftp://files.example/x"},
            {"retailer": "Amazon", "url": "https://amazon.com/dp/1"},
        ]
    )
    # two identical invalid + one ftp invalid + one valid = 4
    assert compute_kr4_7_unique_offer_count(report, {}) == 4
