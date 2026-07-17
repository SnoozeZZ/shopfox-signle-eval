"""Tests for composite report score aggregation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from SingleProductEval.report_composite_score import (
    compute_composite_score,
    compute_offer_info_accuracy,
    compute_section_presence,
    inject_composite_into_raw_metrics,
    map_accuracy_tier,
    map_offer_count_score,
    map_platform_count_score,
    map_product_info_tier,
    map_section_completeness_tier,
)

_PKG_DIR = Path(__file__).resolve().parent
LEICA_REPORT = (
    _PKG_DIR
    / "eval_logs"
    / "report_20260528_032157_Leica_Q3_Condition-Any_report_52d175ad-6568-4e9c-96b6-87f6a687beeb.json"
)


def _minimal_report(
    *,
    offers: list[dict] | None = None,
    images: list[str] | None = None,
    coupon_codes: dict | None = None,
    rebates: list | None = None,
) -> dict:
    report = {
        "spu_metadata": {
            "variant_schema": {"condition": ["New", "Used"]},
            "product_model": "Test Model",
        },
        "defaultSelection": {"condition": "New"},
        "images": images if images is not None else ["https://example.com/img.jpg"],
        "priceComparison": {
            "offers": offers or [],
            "couponCodes": coupon_codes
            if coupon_codes is not None
            else {"coupons": []},
            "rebatesAndCoupons": rebates if rebates is not None else [],
        },
        "reviews": {"summary": "Good product"},
        "socialMediaFeedback": {"posts": [{"text": "nice"}]},
        "expertReviews": {"articles": [{"title": "review"}]},
        "specifications": {"display": [{"name": "weight", "value": "1kg"}]},
    }
    return report


def _offer(retailer: str, url: str = "https://amazon.com/dp/123", price: float = 99.0):
    return {
        "retailer": retailer,
        "url": url,
        "price": price,
        "product_name": "Test Model",
        "condition": "New",
        "variant_attributes": {"condition": "New"},
    }


class TestTierMappings:
    @pytest.mark.parametrize(
        ("count", "expected"),
        [(5, 100), (4, 80), (3, 60), (2, 20), (1, 0), (0, 0)],
    )
    def test_platform_count_tiers(self, count: int, expected: int):
        assert map_platform_count_score(count) == expected

    @pytest.mark.parametrize(
        ("count", "expected"),
        [
            (15, 100),
            (20, 100),
            (14, 70),
            (10, 70),
            (9, 50),
            (8, 50),
            (7, 50),
            (5, 50),
            (4, 0),
            (0, 0),
        ],
    )
    def test_offer_count_tiers(self, count: int, expected: int):
        assert map_offer_count_score(count) == expected

    @pytest.mark.parametrize(
        ("rate", "expected"),
        [(1.0, 100), (0.95, 80), (0.9, 80), (0.85, 60), (0.8, 60), (0.79, 0)],
    )
    def test_accuracy_tiers(self, rate: float, expected: int):
        assert map_accuracy_tier(rate) == expected

    @pytest.mark.parametrize(
        ("rate", "expected"),
        [(1.0, 100), (0.99, 0), (0.5, 0)],
    )
    def test_product_info_binary_tier(self, rate: float, expected: int):
        assert map_product_info_tier(rate) == expected

    @pytest.mark.parametrize(
        ("rate", "expected"),
        [(1.0, 100), (0.833, 50), (0.8, 50), (0.67, 20), (0.65, 20), (0.64, 0)],
    )
    def test_section_completeness_tiers(self, rate: float, expected: int):
        assert map_section_completeness_tier(rate) == expected


class TestOfferInfoIntersection:
    def test_intersection_half_correct_scores_zero(self):
        offers = [_offer(f"Shop{i}") for i in range(30)]
        report = _minimal_report(offers=offers)

        link_correct = {i: True for i in range(30)}
        price_correct = {i: i < 15 for i in range(30)}

        with (
            patch(
                "SingleProductEval.report_composite_score.offer_link_correctness",
                return_value=(link_correct, []),
            ),
            patch(
                "SingleProductEval.report_composite_score.offer_price_correctness",
                return_value=(price_correct, [], {}, []),
            ),
        ):
            accuracy, degraded = compute_offer_info_accuracy(report, {})
            assert accuracy == pytest.approx(0.5)
            assert degraded is False
            assert map_accuracy_tier(accuracy) == 0

    def test_price_degrades_to_link_only(self):
        offers = [_offer("Amazon"), _offer("Walmart")]
        report = _minimal_report(offers=offers)
        link_correct = {0: True, 1: False}

        with (
            patch(
                "SingleProductEval.report_composite_score.offer_link_correctness",
                return_value=(link_correct, []),
            ),
            patch(
                "SingleProductEval.report_composite_score.offer_price_correctness",
                return_value=(None, [], {}, ["crawler unavailable"]),
            ),
        ):
            accuracy, degraded = compute_offer_info_accuracy(report, {})
            assert accuracy == pytest.approx(0.5)
            assert degraded is True


class TestSectionPresence:
    def test_coupon_and_rebate_fields(self):
        report = _minimal_report(
            coupon_codes={"coupons": [{"code": "SAVE10"}]},
            rebates=[{"type": "cashback", "amount": 5}],
        )
        presence = compute_section_presence(report)
        assert presence["coupon"] is True
        assert presence["rebate"] is True

    def test_empty_coupon_and_rebate_not_present(self):
        report = _minimal_report()
        presence = compute_section_presence(report)
        assert presence["coupon"] is False
        assert presence["rebate"] is False


class TestCompositeScore:
    def test_max_score_is_100(self):
        raw = {
            "total_platform_count": 5,
            "total_product_links": 15,
            "sku_spec_display_accuracy": 1.0,
        }
        report = _minimal_report(
            offers=[_offer(f"R{i}") for i in range(15)],
            coupon_codes={"coupons": [{"code": "X"}]},
            rebates=[{"type": "cashback"}],
        )

        with (
            patch(
                "SingleProductEval.report_composite_score.offer_link_correctness",
                return_value=({i: True for i in range(15)}, []),
            ),
            patch(
                "SingleProductEval.report_composite_score.offer_price_correctness",
                return_value=({i: True for i in range(15)}, [], {}, []),
            ),
        ):
            result = compute_composite_score(report, {}, raw)

        assert result["eval_final_score"] == 100.0
        assert result["eval_max_score"] == 100
        dims = result["dimensions"]
        assert dims["platform_count"]["score"] == 100
        assert dims["offer_count"]["score"] == 100
        assert dims["offer_info_accuracy"]["score"] == 100
        assert dims["product_info_accuracy"]["score"] == 100
        assert dims["section_completeness"]["score"] == 100
        for dim in dims.values():
            assert dim["weight"] == 0.2
            assert dim["contribution"] == round(dim["score"] * 0.2, 1)
        assert sum(d["contribution"] for d in dims.values()) == pytest.approx(
            result["eval_final_score"]
        )

    def test_inject_composite_into_raw_metrics(self):
        composite = {
            "eval_final_score": 48.0,
            "dimensions": {
                "platform_count": {"score": 100, "contribution": 20.0},
                "offer_count": {"score": 100, "contribution": 20.0},
                "offer_info_accuracy": {"score": 0, "contribution": 0.0},
                "product_info_accuracy": {"score": 0, "contribution": 0.0},
                "section_completeness": {"score": 50, "contribution": 10.0},
            },
        }
        raw: dict = {}
        inject_composite_into_raw_metrics(raw, composite)
        assert raw["eval_final_score"] == 48.0
        assert raw["eval_dim_platform_count_score"] == 100
        assert raw["eval_dim_platform_count_contrib"] == 20.0
        assert raw["eval_dim_offer_count_score"] == 100
        assert raw["eval_dim_section_completeness_contrib"] == 10.0

    def test_product_info_fails_without_images(self):
        raw = {"sku_spec_display_accuracy": 1.0}
        report = _minimal_report(images=[])
        result = compute_composite_score(report, {}, raw)
        assert result["dimensions"]["product_info_accuracy"]["score"] == 0

    @pytest.mark.skipif(not LEICA_REPORT.exists(), reason="sample report missing")
    def test_leica_report_smoke(self):
        report = json.loads(LEICA_REPORT.read_text(encoding="utf-8"))
        raw: dict = {}
        result = compute_composite_score(report, {}, raw)
        assert "eval_final_score" in result
        assert "dimensions" in result
        assert 0 <= result["eval_final_score"] <= 100
