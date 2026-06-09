"""
Metric computation functions for the SingleProduct eval pipeline.

Each metric function takes (report, ground_truth) and returns a score.
All automated metrics from the eval rubric are implemented here.

Key design: offers are filtered to only those matching the user's default
selection (same logic as the frontend report-viewer), so metrics reflect
what the user actually sees.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from .config import (
    RETAILER_ALIASES,
    TOP3_ECOMMERCE_SLOTS,
    TOP5_EXTRA_SLOTS,
    TOP5_PLATFORM_SLOTS,
)
from .kr3_validators import validate_key_info
from .kr3_8_link_validator import validate_offer_links
from .kr3_9_spu_validator import validate_spu_model_scope
from .kr3_10_sku_spec_validator import validate_sku_spec_display
from .kr3_11_price_validator import validate_offer_prices
from .kr3_12_shipping_validator import validate_shipping_info
from .kr3_13_rebate_validator import validate_rebate_info
from .kr3_19_platform_service_validator import validate_platform_service_info
from .kr4_5_link_completeness_validator import evaluate_kr4_5_link_completeness
from .kr4_platform_offer_validator import evaluate_kr4_platform_offer_threshold

_kr3_1_issues_cache: list[str] = []
_kr3_8_issues_cache: list[dict] = []
_kr3_9_issues_cache: list[dict] = []
_kr3_9_user_model_cache: str = ""
_kr3_9_warnings_cache: list[str] = []
_kr3_10_issues_cache: list[dict] = []
_kr3_10_selection_cache: dict[str, str] = {}
_kr3_10_warnings_cache: list[str] = []
_kr3_11_issues_cache: list[dict] = []
_kr3_11_stats_cache: dict[str, Any] = {}
_kr3_11_warnings_cache: list[str] = []
_kr3_12_issues_cache: list[dict] = []
_kr3_12_stats_cache: dict[str, int] = {}
_kr3_13_issues_cache: list[dict] = []
_kr3_13_stats_cache: dict[str, Any] = {}
_kr3_13_warnings_cache: list[str] = []
_kr3_19_issues_cache: list[dict] = []
_kr3_19_stats_cache: dict[str, int] = {}
_kr4_stats_cache: dict[str, Any] = {}
_kr4_1_stats_cache: dict[str, Any] = {}
_kr4_2_stats_cache: dict[str, Any] = {}

_TOP3_COVERAGE_METRIC_IDS = frozenset({
    "kr4_1_top3_platform_coverage",
    "top3_platform_coverage",
})

_TOP5_COUNT_METRIC_IDS = frozenset({
    "kr4_2_top5_platform_count",
    "top5_platform_count",
})

_TOP3_LINK_COUNT_METRIC_IDS = frozenset({
    "kr4_3_top3_link_count",
    "top3_link_count",
})

_TOP5_LINK_COUNT_METRIC_IDS = frozenset({
    "kr4_4_top5_link_count",
    "top5_link_count",
})

_kr4_3_top3_link_stats_cache: dict[str, Any] = {}
_kr4_4_top5_link_stats_cache: dict[str, Any] = {}
_kr4_5_issues_cache: list[dict] = []
_kr4_5_stats_cache: dict[str, Any] = {}
_kr4_5_warnings_cache: list[str] = []

_KR3_15_METRIC_IDS = frozenset({
    "kr3_15_user_reviews",
    "has_user_reviews",
})
_KR3_16_METRIC_IDS = frozenset({
    "kr3_16_social_media",
    "has_social_media",
})
_KR3_17_METRIC_IDS = frozenset({
    "kr3_17_expert_reviews",
    "has_expert_reviews",
})
_KR3_18_METRIC_IDS = frozenset({
    "kr3_18_attributes",
    "has_attributes",
})
_KR3_CONTENT_METRIC_IDS = (
    _KR3_15_METRIC_IDS
    | _KR3_16_METRIC_IDS
    | _KR3_17_METRIC_IDS
    | _KR3_18_METRIC_IDS
)

_kr3_15_stats_cache: dict[str, Any] = {}
_kr3_16_stats_cache: dict[str, Any] = {}
_kr3_17_stats_cache: dict[str, Any] = {}
_kr3_18_stats_cache: dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_retailer(name: str) -> str:
    """Map raw retailer string to a canonical name."""
    if not name:
        return ""
    key = name.strip().lower()
    if key in RETAILER_ALIASES:
        return RETAILER_ALIASES[key]
    bare = key.replace(".com", "").replace(".co.uk", "")
    if bare in RETAILER_ALIASES:
        return RETAILER_ALIASES[bare]
    return name.strip()


def _url_matches_any_domain(url: str, domains: list[str]) -> bool:
    """Check if a URL belongs to one of the given domains."""
    if not url or not domains:
        return False
    try:
        host = urlparse(url).hostname or ""
        host = host.lower()
        for domain in domains:
            d = domain.lower()
            if host == d or host.endswith("." + d):
                return True
    except Exception:
        pass
    return False


def _fuzzy_contains(haystack: str, needle: str) -> bool:
    """Case-insensitive substring check with basic normalization."""
    if not haystack or not needle:
        return False
    h = haystack.lower().strip()
    n = needle.lower().strip()
    return n in h


def _fuzzy_key_match(target_key: str, keys: dict | set) -> str | None:
    """Find a key in dict/set that fuzzy-matches target_key."""
    target = target_key.lower().replace("_", "").replace("-", "").replace(" ", "")
    target_plural = target + "s"
    target_singular = target.rstrip("s")
    for k in keys:
        k_norm = k.lower().replace("_", "").replace("-", "").replace(" ", "")
        if k_norm in (target, target_plural, target_singular):
            return k
    return None


def _normalize_condition(val: str) -> str:
    """Normalize condition values for comparison (mirrors frontend logic)."""
    normalized = str(val).lower().replace(" ", "-").strip()
    if normalized in ("brandnew", "brand-new"):
        return "new"
    if normalized in ("openbox", "open-box"):
        return "open-box"
    return normalized


def _normalize_variant_value(val: Any) -> str:
    """Lowercase + strip spaces/hyphens for flexible matching."""
    return str(val or "").lower().replace(" ", "").replace("-", "")


def _variant_attributes_match(
    selection: dict[str, str], offer_attrs: dict[str, Any]
) -> bool:
    """Check if an offer's variant_attributes match the given selection."""
    for key, value in selection.items():
        offer_val = offer_attrs.get(key)
        if offer_val is None:
            return False
        if key.lower() == "condition":
            if _normalize_condition(value) != _normalize_condition(str(offer_val)):
                return False
        else:
            if _normalize_variant_value(offer_val) != _normalize_variant_value(value):
                return False
    return True


def _derive_default_selection(report: dict) -> dict[str, str]:
    """Derive the default variant selection from the report — same as frontend.

    Merges:  defaultSelection  →  first option of each variant_schema dim  →  Condition=New fallback
    """
    defaults: dict[str, str] = dict(report.get("defaultSelection") or {})

    spu = report.get("spu_metadata") or {}
    variant_schema = spu.get("variant_schema") or {}
    for dim, options in variant_schema.items():
        if dim not in defaults and isinstance(options, list) and options:
            defaults[dim] = options[0]

    has_condition = any(k.lower() == "condition" for k in defaults)
    if not has_condition:
        defaults["condition"] = "New"

    return defaults


def _get_all_offers(report: dict) -> list[dict]:
    """Extract all offers from a report (unfiltered)."""
    pc = report.get("priceComparison")
    if not isinstance(pc, dict):
        return []
    offers = pc.get("offers", [])
    return offers if isinstance(offers, list) else []


def _get_offers(report: dict) -> list[dict]:
    """Get offers filtered to only those matching the user's default selection."""
    all_offers = _get_all_offers(report)
    if not all_offers:
        return []

    selection = _derive_default_selection(report)
    if not selection:
        return all_offers

    filtered = []
    for o in all_offers:
        va = o.get("variant_attributes")
        if not isinstance(va, dict):
            continue
        if _variant_attributes_match(selection, va):
            filtered.append(o)

    return filtered


def _get_kr3_9_offers(report: dict) -> list[dict]:
    """Offers for KR3-9: variant-filtered and excluding is_target_product=False."""
    return [
        o for o in _get_offers(report)
        if (o.get("metadata") or {}).get("product_identity", {}).get("is_target_product") is not False
    ]


def _resolve_offer_retailer(offer: dict, brand_domains: list[str]) -> str:
    """Resolve offer retailer; URL matching brand_official_domains → Brand Official."""
    url = offer.get("url", "")
    if _url_matches_any_domain(url, brand_domains):
        return "Brand Official"
    return _normalize_retailer(offer.get("retailer", ""))


def _get_distinct_retailers(report: dict, ground_truth: dict) -> set[str]:
    """Get canonical retailer names from filtered offers."""
    offers = _get_offers(report)
    brand_domains = ground_truth.get("brand_official_domains", [])
    return {r for r in (_resolve_offer_retailer(o, brand_domains) for o in offers) if r}


def _slot_covered(retailers: set[str], slot: dict) -> bool:
    """Check if a platform slot is covered by the retailer set."""
    match = slot["match"]
    if isinstance(match, list):
        return any(m in retailers for m in match)
    return match in retailers


def _top3_match_names() -> set[str]:
    """Canonical retailer names that count as top-3 platforms for link counting."""
    names: set[str] = {"Brand Official"}
    for s in TOP3_ECOMMERCE_SLOTS:
        m = s["match"]
        if isinstance(m, list):
            names.update(m)
        else:
            names.add(m)
    return names


def _retailer_for_top3_link_offer(offer: dict, brand_domains: list[str]) -> str:
    return _resolve_offer_retailer(offer, brand_domains)


def _is_top3_link_retailer(retailer: str, top3_names: set[str]) -> bool:
    return retailer in top3_names or retailer == "Brand Official"


def _top5_match_names() -> set[str]:
    """Canonical retailer names that count as top-5 platforms for link counting."""
    names = set(_top3_match_names())
    for s in TOP5_EXTRA_SLOTS:
        m = s["match"]
        if isinstance(m, list):
            names.update(m)
        else:
            names.add(m)
    return names


def _is_top5_link_retailer(retailer: str, top5_names: set[str]) -> bool:
    return retailer in top5_names or retailer == "Brand Official"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A: Intent Recognition — Metrics 1 & 2
# ═══════════════════════════════════════════════════════════════════════════════

def _check_intent_points(report: dict, gt: dict) -> list[dict]:
    """Evaluate the 4 intent points (model, specs, search, comparison)."""
    spu = report.get("spu_metadata") or {}
    default_sel = report.get("defaultSelection") or {}
    offers = _get_offers(report)
    final_rec = report.get("finalRecommendation")
    model_keywords = gt.get("expected_model_keywords", [])
    spec_attrs = gt.get("spec_attributes", {})

    results = []

    # 1. Product model
    report_model = (
        spu.get("product_model", "")
        or spu.get("product_name", "")
        or report.get("name", "")
    )
    covered = bool(report_model)
    correct = covered and any(
        _fuzzy_contains(report_model, kw) for kw in model_keywords
    )
    results.append({"point": "product_model", "covered": covered, "correct": correct})

    # 2. Spec attributes
    if spec_attrs:
        any_spec_found = False
        all_correct = True
        for key, expected_val in spec_attrs.items():
            matched_key = _fuzzy_key_match(key, default_sel)
            if matched_key is not None:
                any_spec_found = True
                actual_val = str(default_sel[matched_key])
                if not _fuzzy_contains(actual_val, expected_val):
                    all_correct = False
            else:
                variant_schema = spu.get("variant_schema", {})
                if _fuzzy_key_match(key, variant_schema):
                    any_spec_found = True
        covered = any_spec_found
        correct = covered and all_correct
    else:
        covered = True
        correct = True
    results.append({"point": "spec_attributes", "covered": covered, "correct": correct})

    # 3. Search action — offers with URLs
    has_offers_with_urls = any(o.get("url") for o in offers)
    covered = has_offers_with_urls
    correct = covered
    results.append({"point": "search_action", "covered": covered, "correct": correct})

    # 4. Comparison action — recommendation present
    has_comparison = (
        isinstance(final_rec, list) and len(final_rec) > 0
    ) or (
        isinstance(report.get("specifications"), list) and len(report.get("specifications", [])) > 0
    )
    covered = has_comparison
    correct = covered
    results.append({"point": "comparison_action", "covered": covered, "correct": correct})

    return results


def compute_intent_coverage(report: dict, gt: dict) -> float:
    points = _check_intent_points(report, gt)
    covered = sum(1 for p in points if p["covered"])
    return covered / len(points)


def compute_intent_accuracy(report: dict, gt: dict) -> float:
    points = _check_intent_points(report, gt)
    covered = [p for p in points if p["covered"]]
    if not covered:
        return 0.0
    correct = sum(1 for p in covered if p["correct"])
    return correct / len(covered)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A2: Run Metrics — KR1 & KR2
# ═══════════════════════════════════════════════════════════════════════════════

def compute_report_success(report: dict, gt: dict) -> str:
    """KR1: complete if report finished; fail on eval error or missing core fields."""
    if report.get("_eval_error"):
        return "fail"
    if report.get("reportType") and report.get("reportType") != "full_report":
        return "fail"
    if not report.get("spu_metadata"):
        return "fail"
    pc = report.get("priceComparison")
    if not isinstance(pc, dict):
        return "fail"
    return "complete"


def compute_duration_minutes(report: dict, gt: dict) -> float | None:
    """KR2: agent execution time in minutes from searchSummary."""
    seconds = (report.get("searchSummary") or {}).get("totalExecutionTimeSeconds")
    if seconds is None:
        return None
    return round(float(seconds) / 60, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A3: Key Info — KR3-1
# ═══════════════════════════════════════════════════════════════════════════════

def compute_key_info_valid(report: dict, gt: dict) -> bool:
    """KR3-1: spec + price-comparison sections structurally valid."""
    global _kr3_1_issues_cache
    valid, issues = validate_key_info(report)
    _kr3_1_issues_cache = issues
    return valid


def get_kr3_1_issues() -> list[str]:
    return list(_kr3_1_issues_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A4: Offer Link Accuracy — KR3-8
# ═══════════════════════════════════════════════════════════════════════════════

def compute_offer_link_accuracy(report: dict, gt: dict) -> float | None:
    """KR3-8: % of filtered offers linking to product detail pages."""
    global _kr3_8_issues_cache
    offers = _get_offers(report)
    accuracy, issues = validate_offer_links(offers)
    _kr3_8_issues_cache = issues
    return accuracy


def get_kr3_8_issues() -> list[dict]:
    return list(_kr3_8_issues_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A5: SPU Model Accuracy — KR3-9
# ═══════════════════════════════════════════════════════════════════════════════

def compute_spu_model_accuracy(report: dict, gt: dict) -> float | None:
    """KR3-9: % of filtered offers whose model+title match user input SPU."""
    global _kr3_9_issues_cache, _kr3_9_user_model_cache, _kr3_9_warnings_cache
    offers = _get_kr3_9_offers(report)
    accuracy, issues, user_model, warnings = validate_spu_model_scope(
        report, gt, offers=offers
    )
    _kr3_9_issues_cache = issues
    _kr3_9_user_model_cache = user_model
    _kr3_9_warnings_cache = warnings
    return accuracy


def get_kr3_9_issues() -> list[dict]:
    return list(_kr3_9_issues_cache)


def get_kr3_9_user_model() -> str:
    return _kr3_9_user_model_cache


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A6: SKU Spec Display Accuracy — KR3-10
# ═══════════════════════════════════════════════════════════════════════════════

def compute_sku_spec_display_accuracy(report: dict, gt: dict) -> float | None:
    """KR3-10: % of filtered offers displaying user-selected specs correctly."""
    global _kr3_10_issues_cache, _kr3_10_selection_cache, _kr3_10_warnings_cache
    offers = _get_offers(report)
    accuracy, issues, user_selection, warnings = validate_sku_spec_display(
        report, offers=offers
    )
    _kr3_10_issues_cache = issues
    _kr3_10_selection_cache = user_selection
    _kr3_10_warnings_cache = warnings
    return accuracy


def get_kr3_10_issues() -> list[dict]:
    return list(_kr3_10_issues_cache)


def get_kr3_10_user_selection() -> dict[str, str]:
    return dict(_kr3_10_selection_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A7: Offer Price Accuracy — KR3-11
# ═══════════════════════════════════════════════════════════════════════════════

def compute_offer_price_accuracy(report: dict, gt: dict) -> float | None:
    """KR3-11: % of evaluable offers whose recorded price matches crawled price."""
    global _kr3_11_issues_cache, _kr3_11_stats_cache, _kr3_11_warnings_cache
    offers = _get_offers(report)
    accuracy, issues, stats, warnings = validate_offer_prices(offers)
    _kr3_11_issues_cache = issues
    _kr3_11_stats_cache = stats
    _kr3_11_warnings_cache = warnings
    return accuracy


def get_kr3_11_issues() -> list[dict]:
    return list(_kr3_11_issues_cache)


def get_kr3_11_stats() -> dict[str, Any]:
    return dict(_kr3_11_stats_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A8: Shipping Info Accuracy — KR3-12
# ═══════════════════════════════════════════════════════════════════════════════

def compute_shipping_info_accuracy(report: dict, gt: dict) -> float | None:
    """KR3-12: % of offers with shipping cost present."""
    global _kr3_12_issues_cache, _kr3_12_stats_cache
    offers = _get_offers(report)
    accuracy, issues, stats = validate_shipping_info(offers)
    _kr3_12_issues_cache = issues
    _kr3_12_stats_cache = stats
    return accuracy


def get_kr3_12_issues() -> list[dict]:
    return list(_kr3_12_issues_cache)


def get_kr3_12_stats() -> dict[str, int]:
    return dict(_kr3_12_stats_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A8b: Rebate Info Accuracy — KR3-13
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rebate_info_accuracy(report: dict, gt: dict) -> float | None:
    """KR3-13: % of verifiable rebate rows matching landing page tier."""
    global _kr3_13_issues_cache, _kr3_13_stats_cache, _kr3_13_warnings_cache
    accuracy, issues, stats, warnings = validate_rebate_info(report, gt)
    _kr3_13_issues_cache = issues
    _kr3_13_stats_cache = stats
    _kr3_13_warnings_cache = warnings
    return accuracy


def get_kr3_13_issues() -> list[dict]:
    return list(_kr3_13_issues_cache)


def get_kr3_13_stats() -> dict[str, Any]:
    return dict(_kr3_13_stats_cache)


def get_kr3_13_warnings() -> list[str]:
    return list(_kr3_13_warnings_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A9: Platform Service Info Accuracy — KR3-19
# ═══════════════════════════════════════════════════════════════════════════════

def compute_platform_service_info_accuracy(report: dict, gt: dict) -> float | None:
    """KR3-19: % of offers with return + delivery present and delivery <= max days."""
    global _kr3_19_issues_cache, _kr3_19_stats_cache
    offers = _get_offers(report)
    accuracy, issues, stats = validate_platform_service_info(offers)
    _kr3_19_issues_cache = issues
    _kr3_19_stats_cache = stats
    return accuracy


def get_kr3_19_issues() -> list[dict]:
    return list(_kr3_19_issues_cache)


def get_kr3_19_stats() -> dict[str, int]:
    return dict(_kr3_19_stats_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP B: Spec Recognition — Metrics 3 & 4
# ═══════════════════════════════════════════════════════════════════════════════

def compute_spec_identification_completeness(report: dict, gt: dict) -> float:
    spec_attrs = gt.get("spec_attributes", {})
    if not spec_attrs:
        return 1.0

    spu = report.get("spu_metadata") or {}
    default_sel = report.get("defaultSelection") or {}
    all_identified: dict[str, str] = {}
    for src in (default_sel, spu.get("variant_schema", {})):
        if isinstance(src, dict):
            all_identified.update({k.lower(): str(v) for k, v in src.items()})

    found = 0
    for key in spec_attrs:
        if _fuzzy_key_match(key, all_identified):
            found += 1
    return found / len(spec_attrs)


def compute_spec_identification_accuracy(report: dict, gt: dict) -> float:
    spec_attrs = gt.get("spec_attributes", {})
    if not spec_attrs:
        return 1.0

    spu = report.get("spu_metadata") or {}
    default_sel = report.get("defaultSelection") or {}

    attempted = 0
    correct = 0
    for key, expected_val in spec_attrs.items():
        matched_key = _fuzzy_key_match(key, default_sel)
        if matched_key is not None:
            attempted += 1
            actual = str(default_sel[matched_key])
            if _fuzzy_contains(actual, expected_val) or _fuzzy_contains(expected_val, actual):
                correct += 1
            continue
        vs = spu.get("variant_schema", {})
        matched_key_vs = _fuzzy_key_match(key, vs)
        if matched_key_vs is not None:
            attempted += 1
            vs_val = vs[matched_key_vs]
            if isinstance(vs_val, list):
                if any(_fuzzy_contains(str(v), expected_val) for v in vs_val):
                    correct += 1
            elif _fuzzy_contains(str(vs_val), expected_val):
                correct += 1

    if attempted == 0:
        return 0.0
    return correct / attempted


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP C: Spec Display Completeness — Metric 5
# ═══════════════════════════════════════════════════════════════════════════════

def compute_spec_display_completeness(report: dict, gt: dict) -> float:
    spec_attrs = gt.get("spec_attributes", {})
    if not spec_attrs:
        return 1.0

    offers = _get_offers(report)
    if not offers:
        return 0.0

    required_keys = set(spec_attrs.keys())
    complete = 0
    for o in offers:
        va = o.get("variant_attributes", {})
        if not isinstance(va, dict):
            continue
        all_present = True
        for rk in required_keys:
            if _fuzzy_key_match(rk, va) is None:
                all_present = False
                break
        if all_present:
            complete += 1

    return complete / len(offers)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP D: Platform Coverage — Metrics 10, 11, 12, 13, 16, 17
# ═══════════════════════════════════════════════════════════════════════════════

def _platform_analysis(report: dict, gt: dict) -> dict[str, Any]:
    """Shared platform analysis used by multiple metrics."""
    offers = _get_offers(report)
    brand_domains = gt.get("brand_official_domains", [])

    retailer_list = [_resolve_offer_retailer(o, brand_domains) for o in offers]
    distinct = {r for r in retailer_list if r}
    has_brand_official = "Brand Official" in distinct

    top3_covered = sum(
        1 for s in TOP3_ECOMMERCE_SLOTS
        if _slot_covered(distinct, s)
    )

    top5_covered = sum(
        1 for s in TOP5_PLATFORM_SLOTS
        if _slot_covered(distinct, s)
    )

    top3_match_names = _top3_match_names()
    top5_match_names = _top5_match_names()

    top3_links = sum(1 for r in retailer_list if r in top3_match_names)
    top5_links = sum(1 for r in retailer_list if r in top5_match_names)

    return {
        "distinct_retailers": distinct,
        "has_brand_official": has_brand_official,
        "total_offers": len(offers),
        "top3_slot_coverage": top3_covered,
        "top5_slot_coverage": top5_covered,
        "top3_link_count": top3_links,
        "top5_link_count": top5_links,
    }


def _build_kr4_1_top3_stats(report: dict, gt: dict) -> tuple[float, dict[str, Any]]:
    pa = _platform_analysis(report, gt)
    distinct = pa["distinct_retailers"]
    has_brand_official = pa["has_brand_official"]
    ecommerce_covered = pa["top3_slot_coverage"]
    brand_bonus = 1 if has_brand_official else 0
    numerator = ecommerce_covered + brand_bonus
    coverage = min(1.0, round(numerator / 3.0, 2))
    slots = [
        {
            "slot": s["slot"],
            "covered": _slot_covered(distinct, s),
        }
        for s in TOP3_ECOMMERCE_SLOTS
    ]
    stats: dict[str, Any] = {
        "ecommerce_slots_covered": ecommerce_covered,
        "brand_official_bonus": bool(brand_bonus),
        "numerator": numerator,
        "denominator": 3,
        "slots_covered": ecommerce_covered,
        "slots_total": 3,
        "coverage": coverage,
        "slots": slots,
        "has_brand_official": has_brand_official,
    }
    return coverage, stats


def _compute_kr4_1_top3_value(report: dict, gt: dict) -> float:
    global _kr4_1_stats_cache
    coverage, stats = _build_kr4_1_top3_stats(report, gt)
    _kr4_1_stats_cache = stats
    return coverage


def compute_kr4_1_top3_platform_coverage(report: dict, gt: dict) -> float:
    """KR4-1: min(1, (ecommerce slots + brand-official bonus) / 3)."""
    return _compute_kr4_1_top3_value(report, gt)


def compute_top3_platform_coverage(report: dict, gt: dict) -> float:
    """Backward-compat alias for kr4_1_top3_platform_coverage."""
    return compute_kr4_1_top3_platform_coverage(report, gt)


def get_kr4_1_stats() -> dict[str, Any]:
    return dict(_kr4_1_stats_cache)


def _build_kr4_2_top5_stats(report: dict, gt: dict) -> tuple[int, dict[str, Any]]:
    pa = _platform_analysis(report, gt)
    distinct = pa["distinct_retailers"]
    has_brand_official = pa["has_brand_official"]
    slots_covered = pa["top5_slot_coverage"]
    slots = [
        {
            "slot": s["slot"],
            "covered": _slot_covered(distinct, s),
        }
        for s in TOP5_PLATFORM_SLOTS
    ]
    stats: dict[str, Any] = {
        "slots_covered": slots_covered,
        "slots_total": 5,
        "slots": slots,
        "has_brand_official": has_brand_official,
    }
    return slots_covered, stats


def _compute_kr4_2_top5_value(report: dict, gt: dict) -> int:
    global _kr4_2_stats_cache
    count, stats = _build_kr4_2_top5_stats(report, gt)
    _kr4_2_stats_cache = stats
    return count


def compute_kr4_2_top5_platform_count(report: dict, gt: dict) -> int:
    """KR4-2: count of covered top5 ecommerce slots (0-5, excludes brand official)."""
    return _compute_kr4_2_top5_value(report, gt)


def compute_top5_platform_count(report: dict, gt: dict) -> int:
    """Backward-compat alias for kr4_2_top5_platform_count."""
    return compute_kr4_2_top5_platform_count(report, gt)


def get_kr4_2_stats() -> dict[str, Any]:
    return dict(_kr4_2_stats_cache)


def compute_total_platform_count(report: dict, gt: dict) -> int:
    pa = _platform_analysis(report, gt)
    return len(pa["distinct_retailers"])


def compute_total_product_links(report: dict, gt: dict) -> int:
    return len(_get_offers(report))


def _build_kr4_3_top3_link_stats(report: dict, gt: dict) -> tuple[int, dict[str, Any]]:
    offers = _get_offers(report)
    pa = _platform_analysis(report, gt)
    top3_names = _top3_match_names()
    brand_domains = gt.get("brand_official_domains", [])
    by_retailer: dict[str, int] = {}
    for o in offers:
        r = _retailer_for_top3_link_offer(o, brand_domains)
        if _is_top3_link_retailer(r, top3_names):
            by_retailer[r] = by_retailer.get(r, 0) + 1
    link_count = pa["top3_link_count"]
    stats: dict[str, Any] = {
        "link_count": link_count,
        "filtered_total": len(offers),
        "by_retailer": by_retailer,
    }
    return link_count, stats


def _compute_kr4_3_top3_link_value(report: dict, gt: dict) -> int:
    global _kr4_3_top3_link_stats_cache
    link_count, stats = _build_kr4_3_top3_link_stats(report, gt)
    _kr4_3_top3_link_stats_cache = stats
    return link_count


def compute_kr4_3_top3_link_count(report: dict, gt: dict) -> int:
    """KR4-3: count of filtered offers from top3 platform retailers."""
    return _compute_kr4_3_top3_link_value(report, gt)


def compute_top3_link_count(report: dict, gt: dict) -> int:
    """Backward-compat alias for kr4_3_top3_link_count."""
    return compute_kr4_3_top3_link_count(report, gt)


def get_kr4_3_top3_link_stats() -> dict[str, Any]:
    return dict(_kr4_3_top3_link_stats_cache)


def _build_kr4_4_top5_link_stats(report: dict, gt: dict) -> tuple[int, dict[str, Any]]:
    offers = _get_offers(report)
    pa = _platform_analysis(report, gt)
    top5_names = _top5_match_names()
    brand_domains = gt.get("brand_official_domains", [])
    by_retailer: dict[str, int] = {}
    for o in offers:
        r = _retailer_for_top3_link_offer(o, brand_domains)
        if _is_top5_link_retailer(r, top5_names):
            by_retailer[r] = by_retailer.get(r, 0) + 1
    link_count = pa["top5_link_count"]
    stats: dict[str, Any] = {
        "link_count": link_count,
        "filtered_total": len(offers),
        "by_retailer": by_retailer,
    }
    return link_count, stats


def _compute_kr4_4_top5_link_value(report: dict, gt: dict) -> int:
    global _kr4_4_top5_link_stats_cache
    link_count, stats = _build_kr4_4_top5_link_stats(report, gt)
    _kr4_4_top5_link_stats_cache = stats
    return link_count


def compute_kr4_4_top5_link_count(report: dict, gt: dict) -> int:
    """KR4-4: count of filtered offers from top5 platform retailers."""
    return _compute_kr4_4_top5_link_value(report, gt)


def compute_top5_link_count(report: dict, gt: dict) -> int:
    """Backward-compat alias for kr4_4_top5_link_count."""
    return compute_kr4_4_top5_link_count(report, gt)


def get_kr4_4_top5_link_stats() -> dict[str, Any]:
    return dict(_kr4_4_top5_link_stats_cache)


def compute_kr4_5_top3_link_completeness(report: dict, gt: dict) -> float | None:
    """KR4-5: crawler-valid top3 URLs found in report top3 offers."""
    global _kr4_5_issues_cache, _kr4_5_stats_cache, _kr4_5_warnings_cache
    offers = _get_offers(report)
    completeness, issues, stats, warnings = evaluate_kr4_5_link_completeness(
        report,
        gt,
        report_offers=offers,
        cache_key=str(gt.get("id") or ""),
    )
    _kr4_5_issues_cache = issues
    _kr4_5_stats_cache = stats
    _kr4_5_warnings_cache = warnings
    return completeness


def get_kr4_5_issues() -> list[dict]:
    return list(_kr4_5_issues_cache)


def get_kr4_5_stats() -> dict[str, Any]:
    return dict(_kr4_5_stats_cache)


def get_kr4_5_warnings() -> list[str]:
    return list(_kr4_5_warnings_cache)


def compute_kr4_3_platform_8_offer(report: dict, gt: dict) -> bool:
    """KR4: filtered offers meet >=3 platforms and >=8 offers."""
    global _kr4_stats_cache
    pa = _platform_analysis(report, gt)
    platform_count = len(pa["distinct_retailers"])
    offer_count = pa["total_offers"]
    passed, stats = evaluate_kr4_platform_offer_threshold(platform_count, offer_count)
    _kr4_stats_cache = stats
    return passed


def get_kr4_stats() -> dict[str, Any]:
    return dict(_kr4_stats_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP E: Boolean Info Checks — Metrics 19, 20, 21, 22
# ═══════════════════════════════════════════════════════════════════════════════

def _has_content(section: Any) -> bool:
    if section is None:
        return False
    if isinstance(section, dict):
        for v in section.values():
            if isinstance(v, list) and len(v) > 0:
                return True
            if isinstance(v, dict) and v:
                return True
            if isinstance(v, str) and v.strip():
                return True
        return False
    if isinstance(section, list):
        return len(section) > 0
    if isinstance(section, str):
        return bool(section.strip())
    return False


def _normalize_specifications(raw: Any) -> Any:
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s
    return raw


def _get_content_section(report: dict, field: str) -> Any:
    raw = report.get(field)
    if field == "specifications":
        return _normalize_specifications(raw)
    return raw


def _content_list_counts(section: Any) -> dict[str, int]:
    if not isinstance(section, dict):
        return {}
    return {k: len(v) for k, v in section.items() if isinstance(v, list)}


def _content_item_count(section: Any) -> int:
    if isinstance(section, list):
        return len(section)
    if isinstance(section, str) and section.strip():
        return 1
    if isinstance(section, dict):
        return sum(_content_list_counts(section).values())
    return 0


def _build_kr3_content_stats(
    report: dict,
    field: str,
    *,
    include_normalized: bool = False,
) -> tuple[bool, dict[str, Any]]:
    raw = report.get(field)
    raw_type = type(raw).__name__ if raw is not None else "null"
    normalized = _get_content_section(report, field)
    present = _has_content(normalized)
    stats: dict[str, Any] = {
        "present": present,
        "raw_type": raw_type,
    }
    if isinstance(normalized, dict):
        stats["list_counts"] = _content_list_counts(normalized)
    if include_normalized:
        stats["normalized_type"] = (
            type(normalized).__name__ if normalized is not None else "null"
        )
        stats["item_count"] = _content_item_count(normalized)
    return present, stats


def _compute_kr3_15_user_reviews_value(report: dict, gt: dict) -> bool:
    global _kr3_15_stats_cache
    present, stats = _build_kr3_content_stats(report, "reviews")
    _kr3_15_stats_cache = stats
    return present


def compute_kr3_15_user_reviews(report: dict, gt: dict) -> bool:
    return _compute_kr3_15_user_reviews_value(report, gt)


def compute_has_user_reviews(report: dict, gt: dict) -> bool:
    return compute_kr3_15_user_reviews(report, gt)


def get_kr3_15_user_reviews_stats() -> dict[str, Any]:
    return dict(_kr3_15_stats_cache)


def _compute_kr3_16_social_media_value(report: dict, gt: dict) -> bool:
    global _kr3_16_stats_cache
    present, stats = _build_kr3_content_stats(report, "socialMediaFeedback")
    _kr3_16_stats_cache = stats
    return present


def compute_kr3_16_social_media(report: dict, gt: dict) -> bool:
    return _compute_kr3_16_social_media_value(report, gt)


def compute_has_social_media(report: dict, gt: dict) -> bool:
    return compute_kr3_16_social_media(report, gt)


def get_kr3_16_social_media_stats() -> dict[str, Any]:
    return dict(_kr3_16_stats_cache)


def _compute_kr3_17_expert_reviews_value(report: dict, gt: dict) -> bool:
    global _kr3_17_stats_cache
    present, stats = _build_kr3_content_stats(report, "expertReviews")
    _kr3_17_stats_cache = stats
    return present


def compute_kr3_17_expert_reviews(report: dict, gt: dict) -> bool:
    return _compute_kr3_17_expert_reviews_value(report, gt)


def compute_has_expert_reviews(report: dict, gt: dict) -> bool:
    return compute_kr3_17_expert_reviews(report, gt)


def get_kr3_17_expert_reviews_stats() -> dict[str, Any]:
    return dict(_kr3_17_stats_cache)


def _compute_kr3_18_attributes_value(report: dict, gt: dict) -> bool:
    global _kr3_18_stats_cache
    present, stats = _build_kr3_content_stats(
        report, "specifications", include_normalized=True
    )
    _kr3_18_stats_cache = stats
    return present


def compute_kr3_18_attributes(report: dict, gt: dict) -> bool:
    return _compute_kr3_18_attributes_value(report, gt)


def compute_has_attributes(report: dict, gt: dict) -> bool:
    return compute_kr3_18_attributes(report, gt)


def get_kr3_18_attributes_stats() -> dict[str, Any]:
    return dict(_kr3_18_stats_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# METRIC DISPATCH TABLE — maps metric id → compute function
# ═══════════════════════════════════════════════════════════════════════════════

METRIC_FUNCTIONS: dict[str, Any] = {
    "report_success": compute_report_success,
    "duration_minutes": compute_duration_minutes,
    "key_info_valid": compute_key_info_valid,
    "offer_link_accuracy": compute_offer_link_accuracy,
    "spu_model_accuracy": compute_spu_model_accuracy,
    "sku_spec_display_accuracy": compute_sku_spec_display_accuracy,
    "offer_price_accuracy": compute_offer_price_accuracy,
    "shipping_info_accuracy": compute_shipping_info_accuracy,
    "rebate_info_accuracy": compute_rebate_info_accuracy,
    "platform_service_info_accuracy": compute_platform_service_info_accuracy,
    "intent_coverage": compute_intent_coverage,
    "intent_accuracy": compute_intent_accuracy,
    "spec_id_completeness": compute_spec_identification_completeness,
    "spec_id_accuracy": compute_spec_identification_accuracy,
    "spec_display_completeness": compute_spec_display_completeness,
    "kr4_3_platform_8_offer": compute_kr4_3_platform_8_offer,
    "kr4_1_top3_platform_coverage": compute_kr4_1_top3_platform_coverage,
    "top3_platform_coverage": compute_top3_platform_coverage,
    "kr4_2_top5_platform_count": compute_kr4_2_top5_platform_count,
    "top5_platform_count": compute_top5_platform_count,
    "total_platform_count": compute_total_platform_count,
    "total_product_links": compute_total_product_links,
    "kr4_3_top3_link_count": compute_kr4_3_top3_link_count,
    "top3_link_count": compute_top3_link_count,
    "kr4_4_top5_link_count": compute_kr4_4_top5_link_count,
    "top5_link_count": compute_top5_link_count,
    "kr4_5_top3_link_completeness": compute_kr4_5_top3_link_completeness,
    "kr3_15_user_reviews": compute_kr3_15_user_reviews,
    "has_user_reviews": compute_has_user_reviews,
    "kr3_16_social_media": compute_kr3_16_social_media,
    "has_social_media": compute_has_social_media,
    "kr3_17_expert_reviews": compute_kr3_17_expert_reviews,
    "has_expert_reviews": compute_has_expert_reviews,
    "kr3_18_attributes": compute_kr3_18_attributes,
    "has_attributes": compute_has_attributes,
}


# ═══════════════════════════════════════════════════════════════════════════════
# AGGREGATOR: Compute metrics (only enabled ones)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_all_metrics(
    report: dict,
    gt: dict,
    enabled_metrics: list[str] | None = None,
) -> dict[str, Any]:
    """
    Compute metrics for a single (report, ground_truth) pair.
    Only computes metrics listed in enabled_metrics (defaults to all).
    Returns a flat dict of metric_name → value.
    """
    if enabled_metrics is None:
        enabled_metrics = list(METRIC_FUNCTIONS.keys())

    if report.get("_eval_error"):
        result: dict[str, Any] = {"_error": report["_eval_error"]}
        for mid in enabled_metrics:
            result[mid] = None
        return result

    result = {}
    top3_enabled = _TOP3_COVERAGE_METRIC_IDS.intersection(enabled_metrics)
    top5_enabled = _TOP5_COUNT_METRIC_IDS.intersection(enabled_metrics)
    top3_link_enabled = _TOP3_LINK_COUNT_METRIC_IDS.intersection(enabled_metrics)
    top5_link_enabled = _TOP5_LINK_COUNT_METRIC_IDS.intersection(enabled_metrics)
    kr3_15_enabled = _KR3_15_METRIC_IDS.intersection(enabled_metrics)
    kr3_16_enabled = _KR3_16_METRIC_IDS.intersection(enabled_metrics)
    kr3_17_enabled = _KR3_17_METRIC_IDS.intersection(enabled_metrics)
    kr3_18_enabled = _KR3_18_METRIC_IDS.intersection(enabled_metrics)
    skip_ids = (
        _TOP3_COVERAGE_METRIC_IDS
        | _TOP5_COUNT_METRIC_IDS
        | _TOP3_LINK_COUNT_METRIC_IDS
        | _TOP5_LINK_COUNT_METRIC_IDS
        | _KR3_CONTENT_METRIC_IDS
    )
    for mid in enabled_metrics:
        if mid in skip_ids:
            continue
        fn = METRIC_FUNCTIONS.get(mid)
        if fn:
            try:
                result[mid] = fn(report, gt)
            except Exception as exc:
                result[mid] = None
                result.setdefault("_warnings", []).append(f"{mid}: {exc}")

    if top3_enabled:
        try:
            top3_value = _compute_kr4_1_top3_value(report, gt)
            for mid in top3_enabled:
                result[mid] = top3_value
        except Exception as exc:
            for mid in top3_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr4_1_top3: {exc}")

    if top5_enabled:
        try:
            top5_value = _compute_kr4_2_top5_value(report, gt)
            for mid in top5_enabled:
                result[mid] = top5_value
        except Exception as exc:
            for mid in top5_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr4_2_top5: {exc}")

    if top3_link_enabled:
        try:
            top3_link_value = _compute_kr4_3_top3_link_value(report, gt)
            for mid in top3_link_enabled:
                result[mid] = top3_link_value
        except Exception as exc:
            for mid in top3_link_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr4_3_top3_link: {exc}")

    if top5_link_enabled:
        try:
            top5_link_value = _compute_kr4_4_top5_link_value(report, gt)
            for mid in top5_link_enabled:
                result[mid] = top5_link_value
        except Exception as exc:
            for mid in top5_link_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr4_4_top5_link: {exc}")

    if kr3_15_enabled:
        try:
            kr3_15_value = _compute_kr3_15_user_reviews_value(report, gt)
            for mid in kr3_15_enabled:
                result[mid] = kr3_15_value
        except Exception as exc:
            for mid in kr3_15_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr3_15_user_reviews: {exc}")

    if kr3_16_enabled:
        try:
            kr3_16_value = _compute_kr3_16_social_media_value(report, gt)
            for mid in kr3_16_enabled:
                result[mid] = kr3_16_value
        except Exception as exc:
            for mid in kr3_16_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr3_16_social_media: {exc}")

    if kr3_17_enabled:
        try:
            kr3_17_value = _compute_kr3_17_expert_reviews_value(report, gt)
            for mid in kr3_17_enabled:
                result[mid] = kr3_17_value
        except Exception as exc:
            for mid in kr3_17_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr3_17_expert_reviews: {exc}")

    if kr3_18_enabled:
        try:
            kr3_18_value = _compute_kr3_18_attributes_value(report, gt)
            for mid in kr3_18_enabled:
                result[mid] = kr3_18_value
        except Exception as exc:
            for mid in kr3_18_enabled:
                result[mid] = None
            result.setdefault("_warnings", []).append(f"kr3_18_attributes: {exc}")

    if "key_info_valid" in enabled_metrics:
        result["_kr3_1_issues"] = get_kr3_1_issues()

    if "offer_link_accuracy" in enabled_metrics:
        result["_kr3_8_issues"] = get_kr3_8_issues()

    if "spu_model_accuracy" in enabled_metrics:
        result["_kr3_9_issues"] = get_kr3_9_issues()
        result["_kr3_9_user_model"] = get_kr3_9_user_model()
        if _kr3_9_warnings_cache:
            result.setdefault("_warnings", []).extend(_kr3_9_warnings_cache)

    if "sku_spec_display_accuracy" in enabled_metrics:
        result["_kr3_10_issues"] = get_kr3_10_issues()
        result["_kr3_10_user_selection"] = get_kr3_10_user_selection()
        if _kr3_10_warnings_cache:
            result.setdefault("_warnings", []).extend(_kr3_10_warnings_cache)

    if "offer_price_accuracy" in enabled_metrics:
        result["_kr3_11_issues"] = get_kr3_11_issues()
        result["_kr3_11_stats"] = get_kr3_11_stats()
        if _kr3_11_warnings_cache:
            result.setdefault("_warnings", []).extend(_kr3_11_warnings_cache)

    if "shipping_info_accuracy" in enabled_metrics:
        result["_kr3_12_issues"] = get_kr3_12_issues()
        result["_kr3_12_stats"] = get_kr3_12_stats()

    if "rebate_info_accuracy" in enabled_metrics:
        result["_kr3_13_issues"] = get_kr3_13_issues()
        result["_kr3_13_stats"] = get_kr3_13_stats()
        if _kr3_13_warnings_cache:
            result.setdefault("_warnings", []).extend(_kr3_13_warnings_cache)

    if "platform_service_info_accuracy" in enabled_metrics:
        result["_kr3_19_issues"] = get_kr3_19_issues()
        result["_kr3_19_stats"] = get_kr3_19_stats()

    if "kr4_3_platform_8_offer" in enabled_metrics:
        result["_kr4_stats"] = get_kr4_stats()

    if top3_enabled:
        result["_kr4_1_stats"] = get_kr4_1_stats()

    if top5_enabled:
        result["_kr4_2_stats"] = get_kr4_2_stats()

    if top3_link_enabled:
        result["_kr4_3_top3_link_stats"] = get_kr4_3_top3_link_stats()

    if top5_link_enabled:
        result["_kr4_4_top5_link_stats"] = get_kr4_4_top5_link_stats()

    if "kr4_5_top3_link_completeness" in enabled_metrics:
        result["_kr4_5_issues"] = get_kr4_5_issues()
        result["_kr4_5_stats"] = get_kr4_5_stats()
        if _kr4_5_warnings_cache:
            result.setdefault("_warnings", []).extend(_kr4_5_warnings_cache)

    if kr3_15_enabled:
        result["_kr3_15_user_reviews_stats"] = get_kr3_15_user_reviews_stats()

    if kr3_16_enabled:
        result["_kr3_16_social_media_stats"] = get_kr3_16_social_media_stats()

    if kr3_17_enabled:
        result["_kr3_17_expert_reviews_stats"] = get_kr3_17_expert_reviews_stats()

    if kr3_18_enabled:
        result["_kr3_18_attributes_stats"] = get_kr3_18_attributes_stats()

    return result
