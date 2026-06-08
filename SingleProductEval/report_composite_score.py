"""
Composite report score: 5 SKU dimensions, equal weight 0.2 each.

All offer-related dimensions use filtered offers from metrics._get_offers.
"""

from __future__ import annotations

from typing import Any

from .config import (
    COMPOSITE_ACCURACY_TIERS,
    COMPOSITE_OFFER_COUNT_TIERS,
    COMPOSITE_PLATFORM_COUNT_TIERS,
    COMPOSITE_SCORE_MAX_POSSIBLE,
    COMPOSITE_SCORE_WEIGHT,
    COMPOSITE_SECTION_COMPLETENESS_TIERS,
)
from .kr3_10_sku_spec_validator import validate_sku_spec_display
from .kr3_11_price_validator import offer_price_correctness
from .kr3_8_link_validator import offer_link_correctness
from .kr3_validators import validate_images_structure
from .metrics import (
    _build_kr3_content_stats,
    _get_content_section,
    _get_offers,
    _has_content,
    _platform_analysis,
)

_SECTION_KEYS = (
    "coupon",
    "rebate",
    "reviews",
    "social_media",
    "expert_reviews",
    "attributes",
)


def _map_count_tier(count: int, tiers: list[tuple[int, int]]) -> int:
    for min_count, score in sorted(tiers, key=lambda item: item[0], reverse=True):
        if count >= min_count:
            return score
    return 0


def _map_rate_tier(rate: float, tiers: list[tuple[float, int]]) -> int:
    for min_rate, score in sorted(tiers, key=lambda item: item[0], reverse=True):
        if rate >= min_rate:
            return score
    return 0


def map_platform_count_score(count: int) -> int:
    return _map_count_tier(count, COMPOSITE_PLATFORM_COUNT_TIERS)


def map_offer_count_score(count: int) -> int:
    return _map_count_tier(count, COMPOSITE_OFFER_COUNT_TIERS)


def map_accuracy_tier(rate: float) -> int:
    return _map_rate_tier(rate, COMPOSITE_ACCURACY_TIERS)


def map_product_info_tier(rate: float) -> int:
    return 100 if rate >= 1.0 else 0


def map_section_completeness_tier(rate: float) -> int:
    return _map_rate_tier(rate, COMPOSITE_SECTION_COMPLETENESS_TIERS)


def _resolve_platform_count(report: dict, gt: dict, raw_metrics: dict) -> int:
    value = raw_metrics.get("total_platform_count")
    if value is not None:
        return int(value)
    pa = _platform_analysis(report, gt)
    return len(pa["distinct_retailers"])


def _resolve_offer_count(report: dict, raw_metrics: dict) -> int:
    value = raw_metrics.get("total_product_links")
    if value is not None:
        return int(value)
    return len(_get_offers(report))


def compute_offer_info_accuracy(
    report: dict,
    gt: dict,
) -> tuple[float | None, bool]:
    """
    Per-offer intersection of link + price correctness on filtered offers.

    Returns (accuracy 0~1 or None, degraded).
    When price is globally unavailable, degrades to link accuracy only.
    """
    del gt
    offers = _get_offers(report)
    if not offers:
        return None, False

    link_correct, _ = offer_link_correctness(offers)
    price_correct, _, _, _ = offer_price_correctness(offers)

    if price_correct is None:
        correct = sum(1 for i in range(len(offers)) if link_correct.get(i, False))
        return correct / len(offers), True

    correct = sum(
        1
        for i in range(len(offers))
        if link_correct.get(i, False) and price_correct.get(i, False)
    )
    return correct / len(offers), False


def compute_product_info_rate(report: dict, raw_metrics: dict) -> float:
    images_ok = validate_images_structure(report)
    offers = _get_offers(report)

    spec_accuracy = raw_metrics.get("sku_spec_display_accuracy")
    if spec_accuracy is None and offers:
        spec_accuracy, _, _, _ = validate_sku_spec_display(report, offers=offers)
    if spec_accuracy is None:
        spec_accuracy = 0.0

    if images_ok and spec_accuracy >= 1.0:
        return 1.0
    return 0.0 if not images_ok else float(spec_accuracy)


def _has_coupon_codes(report: dict) -> bool:
    pc = report.get("priceComparison") or {}
    coupon_codes = pc.get("couponCodes")
    if not isinstance(coupon_codes, dict):
        return False
    coupons = coupon_codes.get("coupons")
    return isinstance(coupons, list) and len(coupons) > 0


def _has_rebates(report: dict) -> bool:
    pc = report.get("priceComparison") or {}
    rebates = pc.get("rebatesAndCoupons")
    return isinstance(rebates, list) and len(rebates) > 0


def compute_section_presence(report: dict) -> dict[str, bool]:
    reviews_present, _ = _build_kr3_content_stats(report, "reviews")
    social_present, _ = _build_kr3_content_stats(report, "socialMediaFeedback")
    expert_present, _ = _build_kr3_content_stats(report, "expertReviews")
    attrs_section = _get_content_section(report, "specifications")
    attrs_present = _has_content(attrs_section)

    return {
        "coupon": _has_coupon_codes(report),
        "rebate": _has_rebates(report),
        "reviews": reviews_present,
        "social_media": social_present,
        "expert_reviews": expert_present,
        "attributes": attrs_present,
    }


def compute_section_completeness_rate(report: dict) -> tuple[float, int, dict[str, bool]]:
    presence = compute_section_presence(report)
    present_count = sum(1 for key in _SECTION_KEYS if presence[key])
    return present_count / 6, present_count, presence


def compute_composite_score(
    report: dict,
    gt: dict,
    raw_metrics: dict,
) -> dict[str, Any]:
    platform_raw = _resolve_platform_count(report, gt, raw_metrics)
    offer_count_raw = _resolve_offer_count(report, raw_metrics)
    offer_info_raw, degraded = compute_offer_info_accuracy(report, gt)
    product_info_raw = compute_product_info_rate(report, raw_metrics)
    section_rate, section_present, section_presence = compute_section_completeness_rate(
        report
    )

    platform_score = map_platform_count_score(platform_raw)
    offer_count_score = map_offer_count_score(offer_count_raw)
    offer_info_score = (
        map_accuracy_tier(offer_info_raw) if offer_info_raw is not None else 0
    )
    product_info_score = map_product_info_tier(product_info_raw)
    section_score = map_section_completeness_tier(section_rate)

    dimension_scores = [
        platform_score,
        offer_count_score,
        offer_info_score,
        product_info_score,
        section_score,
    ]
    total = round(sum(dimension_scores) * COMPOSITE_SCORE_WEIGHT, 1)

    return {
        "eval_final_score": total,
        "eval_max_score": COMPOSITE_SCORE_MAX_POSSIBLE,
        "dimensions": {
            "platform_count": {"raw": platform_raw, "score": platform_score},
            "offer_count": {"raw": offer_count_raw, "score": offer_count_score},
            "offer_info_accuracy": {
                "raw": offer_info_raw,
                "score": offer_info_score,
                "degraded": degraded,
            },
            "product_info_accuracy": {
                "raw": product_info_raw,
                "score": product_info_score,
            },
            "section_completeness": {
                "raw": round(section_rate, 4),
                "present": section_present,
                "score": section_score,
                "sections": section_presence,
            },
        },
    }
