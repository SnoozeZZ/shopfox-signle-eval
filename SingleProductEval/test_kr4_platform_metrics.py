"""Tests for KR4-1 ~ KR4-4 platform coverage and link count metrics."""

from __future__ import annotations

from SingleProductEval.metrics import (
    _build_kr4_1_top3_stats,
    _build_kr4_2_top5_stats,
    _build_kr4_3_top3_link_stats,
    _build_kr4_4_top5_link_stats,
)


def _make_report(
    retailers: list[str],
    *,
    extra_offers: list[dict] | None = None,
    default_selection: dict | None = None,
) -> dict:
    selection = default_selection or {"condition": "New"}
    offers = [
        {
            "retailer": r,
            "url": f"https://{r.lower().replace(' ', '')}.com/p",
            "variant_attributes": dict(selection),
        }
        for r in retailers
    ]
    if extra_offers:
        offers.extend(extra_offers)
    return {
        "defaultSelection": selection,
        "priceComparison": {"offers": offers},
    }


def test_kr4_1_three_ecommerce_platforms_is_full_coverage():
    report = _make_report(["Amazon", "Walmart", "Best Buy"])
    gt = {"brand_official_domains": []}
    coverage, stats = _build_kr4_1_top3_stats(report, gt)
    assert coverage == 1.0
    assert stats["ecommerce_slots_covered"] == 3
    assert stats["brand_official_bonus"] is False
    assert stats["numerator"] == 3


def test_kr4_1_two_ecommerce_platforms_is_two_thirds():
    report = _make_report(["Amazon", "Walmart"])
    gt = {"brand_official_domains": []}
    coverage, stats = _build_kr4_1_top3_stats(report, gt)
    assert coverage == 0.67
    assert stats["ecommerce_slots_covered"] == 2
    assert stats["numerator"] == 2


def test_kr4_1_single_ecommerce_platform_is_one_third():
    report = _make_report(["Amazon"])
    gt = {"brand_official_domains": []}
    coverage, stats = _build_kr4_1_top3_stats(report, gt)
    assert coverage == 0.33
    assert stats["ecommerce_slots_covered"] == 1


def test_kr4_1_brand_official_bonus_caps_at_one():
    report = _make_report(
        ["Amazon", "Walmart"],
        extra_offers=[
            {
                "retailer": "Samsung",
                "url": "https://www.samsung.com/us/p",
                "variant_attributes": {"condition": "New"},
            },
        ],
    )
    gt = {"brand_official_domains": ["samsung.com"]}
    coverage, stats = _build_kr4_1_top3_stats(report, gt)
    assert coverage == 1.0
    assert stats["ecommerce_slots_covered"] == 2
    assert stats["brand_official_bonus"] is True
    assert stats["numerator"] == 3


def test_kr4_1_all_ecommerce_plus_brand_official_capped_at_one():
    report = _make_report(
        ["Amazon", "Walmart", "Best Buy"],
        extra_offers=[
            {
                "retailer": "Samsung",
                "url": "https://www.samsung.com/us/p",
                "variant_attributes": {"condition": "New"},
            },
        ],
    )
    gt = {"brand_official_domains": ["samsung.com"]}
    coverage, stats = _build_kr4_1_top3_stats(report, gt)
    assert coverage == 1.0
    assert stats["numerator"] == 4


def test_kr4_2_top5_counts_ecommerce_slots_only():
    report = _make_report(["Amazon", "Walmart", "Best Buy", "eBay", "Target"])
    gt = {"brand_official_domains": []}
    count, stats = _build_kr4_2_top5_stats(report, gt)
    assert count == 5
    assert all(s["covered"] for s in stats["slots"])


def test_kr4_2_three_ecommerce_without_brand_official():
    report = _make_report(["Amazon", "Walmart", "Best Buy"])
    gt = {"brand_official_domains": []}
    count, _ = _build_kr4_2_top5_stats(report, gt)
    assert count == 3


def test_kr4_2_brand_official_not_counted_in_top5():
    report = _make_report(
        ["Amazon", "Walmart", "Best Buy"],
        extra_offers=[
            {
                "retailer": "Samsung",
                "url": "https://www.samsung.com/us/p",
                "variant_attributes": {"condition": "New"},
            },
        ],
    )
    gt = {"brand_official_domains": ["samsung.com"]}
    count, _ = _build_kr4_2_top5_stats(report, gt)
    assert count == 3


def test_kr4_3_link_count_includes_brand_official_by_url():
    report = _make_report(
        ["Amazon", "Walmart", "Best Buy"],
        extra_offers=[
            {
                "retailer": "Samsung",
                "url": "https://www.samsung.com/us/p",
                "variant_attributes": {"condition": "New"},
            },
        ],
    )
    gt = {"brand_official_domains": ["samsung.com"]}
    link_count, stats = _build_kr4_3_top3_link_stats(report, gt)
    assert link_count == 4
    assert stats["by_retailer"]["Brand Official"] == 1


def test_kr4_3_link_count_basic():
    report = _make_report(["Amazon", "Walmart", "Best Buy"])
    gt = {"brand_official_domains": []}
    link_count, stats = _build_kr4_3_top3_link_stats(report, gt)
    assert link_count == 3
    assert stats["by_retailer"] == {"Amazon": 1, "Walmart": 1, "Best Buy": 1}


def test_kr4_4_top5_link_count():
    report = _make_report(["Amazon", "Walmart", "Best Buy", "eBay", "Target"])
    gt = {"brand_official_domains": []}
    link_count, stats = _build_kr4_4_top5_link_stats(report, gt)
    assert link_count == 5
    assert len(stats["by_retailer"]) == 5


def test_all_offers_counted_regardless_of_default_selection():
    report = {
        "defaultSelection": {"condition": "New", "color": "Black"},
        "priceComparison": {
            "offers": [
                {
                    "retailer": "Amazon",
                    "url": "https://amazon.com/p",
                    "variant_attributes": {"condition": "New", "color": "Black"},
                },
                {
                    "retailer": "Walmart",
                    "url": "https://walmart.com/p",
                    "variant_attributes": {"condition": "New", "color": "White"},
                },
                {
                    "retailer": "Best Buy",
                    "url": "https://bestbuy.com/p",
                    "variant_attributes": {"condition": "New", "color": "Black"},
                },
            ]
        },
    }
    gt = {"brand_official_domains": []}
    coverage, stats = _build_kr4_1_top3_stats(report, gt)
    assert coverage == 1.0
    assert stats["ecommerce_slots_covered"] == 3
    link_count, stats3 = _build_kr4_3_top3_link_stats(report, gt)
    assert link_count == 3
    assert stats3["offer_total"] == 3


def test_kr4_uses_all_offers_mixed_conditions():
    report = {
        "defaultSelection": {"Condition": "New"},
        "priceComparison": {
            "offers": [
                {
                    "retailer": "Amazon",
                    "url": "https://amazon.com/1",
                    "variant_attributes": {"Condition": "New"},
                },
                {
                    "retailer": "Amazon",
                    "url": "https://amazon.com/2",
                    "variant_attributes": {"Condition": "Used"},
                },
                {
                    "retailer": "Walmart",
                    "url": "https://walmart.com/1",
                    "variant_attributes": {"Condition": "New"},
                },
                {
                    "retailer": "Best Buy",
                    "url": "https://bestbuy.com/1",
                    "variant_attributes": {"Condition": "Refurbished"},
                },
                {
                    "retailer": "eBay",
                    "url": "https://ebay.com/1",
                    "variant_attributes": {"Condition": "Used"},
                },
            ]
        },
    }
    gt = {"brand_official_domains": []}
    _, stats3 = _build_kr4_3_top3_link_stats(report, gt)
    _, stats4 = _build_kr4_4_top5_link_stats(report, gt)
    assert stats3["offer_total"] == 5
    assert stats3["link_count"] == 4  # 2 Amazon + Walmart + Best Buy
    assert stats4["offer_total"] == 5
    assert stats4["link_count"] == 5  # all five retailers in top5 set
