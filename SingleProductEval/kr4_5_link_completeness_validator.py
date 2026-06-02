"""
KR4-5: Top3 link completeness — crawler reference URLs vs report top3 offer URLs.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .category_expand_client import expand_category
from .config import (
    KR3_9_LLM_BATCH_SIZE,
    KR3_9_USE_LLM,
    KR4_5_CRAWLER_PLATFORMS,
    KR4_5_ECOMMERCE_RETAILERS,
    KR4_5_ISSUES_MAX,
    RETAILER_ALIASES,
)
from .kr3_9_spu_validator import (
    _llm_judge_batch,
    _route_offer,
    derive_user_model,
)
from .llm_client import has_dashscope_api_key
from .url_normalize import normalize_url


def build_crawler_keywords(report: dict, gt: dict) -> list[str]:
    """Single keyword string for category/expand."""
    parts: list[str] = []
    sku = gt.get("sku_discovery_data") or {}
    analysis = sku.get("product_analysis") or {}
    cat = str(analysis.get("category") or "").strip()
    model = str(gt.get("model") or "").strip()
    if cat:
        parts.append(cat)
    if model:
        parts.append(model)
    if not parts:
        parts.append(str(gt.get("category") or "").strip())
        if model and str(gt.get("category") or "").strip() not in parts:
            parts.append(model)
    if not model:
        um = derive_user_model(report, gt)
        if um:
            parts.append(um)
    text = " ".join(p for p in parts if p).strip()
    return [text] if text else []


def crawler_item_to_offer(item: dict[str, str]) -> dict[str, str]:
    platform = str(item.get("platform") or "").strip().lower()
    retailer = ""
    if "amazon" in platform:
        retailer = "Amazon"
    elif "walmart" in platform:
        retailer = "Walmart"
    elif "bestbuy" in platform or "best buy" in platform:
        retailer = "Best Buy"
    return {
        "product_model": str(item.get("product_model") or ""),
        "product_name": str(item.get("product_name") or ""),
        "retailer": retailer,
        "url": str(item.get("url") or ""),
    }


def filter_crawler_items_by_spu(
    items: list[dict[str, str]],
    report: dict,
    gt: dict,
) -> tuple[list[dict[str, str]], dict[str, int], list[str]]:
    """
    Keep crawler rows that match target SPU (KR3-9 route + LLM).
    Returns (valid_items, spu_filter_stats, warnings).
    """
    user_model = derive_user_model(report, gt)
    warnings: list[str] = []
    stats = {
        "exact_match": 0,
        "llm_match": 0,
        "rejected": 0,
        "llm_skipped": 0,
    }
    if not user_model:
        warnings.append("kr4_5: no user_model derived; crawler denominator empty")
        return [], stats, warnings

    valid: list[dict[str, str]] = []
    llm_queue: list[tuple[int, dict, dict[str, str]]] = []

    for i, item in enumerate(items):
        offer = crawler_item_to_offer(item)
        route = _route_offer(offer, user_model)
        if route == "exact_match":
            valid.append(item)
            stats["exact_match"] += 1
        elif route == "empty_mismatch":
            stats["rejected"] += 1
        else:
            llm_queue.append((i, offer, item))

    use_llm = KR3_9_USE_LLM and has_dashscope_api_key()
    if llm_queue and not use_llm:
        stats["llm_skipped"] += len(llm_queue)
        warnings.append(
            f"kr4_5: KR3-9 LLM unavailable, {len(llm_queue)} crawler items skipped from denominator"
        )
        return valid, stats, warnings

    if llm_queue and use_llm:
        for start in range(0, len(llm_queue), KR3_9_LLM_BATCH_SIZE):
            batch = llm_queue[start : start + KR3_9_LLM_BATCH_SIZE]
            try:
                llm_results = _llm_judge_batch(
                    user_model, [(idx, offer) for idx, offer, _ in batch]
                )
            except Exception as exc:
                stats["llm_skipped"] += len(batch)
                warnings.append(f"kr4_5: LLM batch failed: {str(exc)[:200]}")
                continue

            for idx, offer, item in batch:
                if idx not in llm_results:
                    stats["rejected"] += 1
                    continue
                matched, _reason = llm_results[idx]
                if matched:
                    valid.append(item)
                    stats["llm_match"] += 1
                else:
                    stats["rejected"] += 1

    return valid, stats, warnings


def _normalize_retailer(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    if key in RETAILER_ALIASES:
        return RETAILER_ALIASES[key]
    bare = key.replace(".com", "").replace(".co.uk", "")
    if bare in RETAILER_ALIASES:
        return RETAILER_ALIASES[bare]
    return name.strip()


def _is_valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _is_brand_official_offer(offer: dict, brand_domains: list[str]) -> bool:
    url = str(offer.get("url") or "")
    if not brand_domains or not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    for domain in brand_domains:
        d = str(domain).lower()
        if host == d or host.endswith("." + d):
            return True
    return False


def collect_report_top3_urls(
    offers: list[dict],
    brand_domains: list[str],
) -> tuple[set[str], int, dict[str, int]]:
    """
    Top3 ecommerce offers only (excludes Brand Official).
    Returns (normalized_urls, offer_count, by_retailer).
    """
    urls: set[str] = set()
    by_retailer: dict[str, int] = {}
    count = 0

    for offer in offers:
        retailer = _normalize_retailer(str(offer.get("retailer") or ""))
        if retailer == "Brand Official" or _is_brand_official_offer(offer, brand_domains):
            continue
        if retailer not in KR4_5_ECOMMERCE_RETAILERS:
            continue
        url = str(offer.get("url") or "").strip()
        if not _is_valid_http_url(url):
            continue
        norm = normalize_url(url)
        if not norm:
            continue
        count += 1
        urls.add(norm)
        by_retailer[retailer] = by_retailer.get(retailer, 0) + 1

    return urls, count, by_retailer


def evaluate_kr4_5_link_completeness(
    report: dict,
    gt: dict,
    *,
    report_offers: list[dict],
    cache_key: str | None = None,
) -> tuple[float | None, list[dict], dict[str, Any], list[str]]:
    """Returns (completeness, issues, stats, warnings)."""
    warnings: list[str] = []
    stats: dict[str, Any] = {
        "keywords": [],
        "platforms": list(KR4_5_CRAWLER_PLATFORMS),
        "crawler_source": None,
        "crawler_raw_count": 0,
        "crawler_after_spu_count": 0,
        "crawler_unique_urls": 0,
        "report_top3_offer_count": 0,
        "report_unique_urls": 0,
        "matched_count": 0,
        "completeness": None,
        "extra_in_report_count": 0,
        "by_platform": {},
        "spu_filter": {},
    }
    issues: list[dict] = []

    keywords = build_crawler_keywords(report, gt)
    stats["keywords"] = keywords
    if not keywords:
        warnings.append("kr4_5: empty crawler keywords")
        return None, issues, stats, warnings

    brand_domains = gt.get("brand_official_domains") or []
    report_urls, report_offer_count, report_by_retailer = collect_report_top3_urls(
        report_offers, brand_domains
    )
    stats["report_top3_offer_count"] = report_offer_count
    stats["report_unique_urls"] = len(report_urls)
    stats["report_by_retailer"] = report_by_retailer

    ck = cache_key or str(gt.get("id") or "unknown")
    try:
        raw_items, source = expand_category(
            keywords,
            list(KR4_5_CRAWLER_PLATFORMS),
            cache_key=ck,
        )
        stats["crawler_source"] = source
        if source == "fixture":
            warnings.append("kr4_5: using fixture fallback for category expand")
    except Exception as exc:
        warnings.append(f"kr4_5: category expand failed: {str(exc)[:200]}")
        return None, issues, stats, warnings

    stats["crawler_raw_count"] = len(raw_items)
    valid_items, spu_stats, spu_warnings = filter_crawler_items_by_spu(
        raw_items, report, gt
    )
    warnings.extend(spu_warnings)
    stats["spu_filter"] = spu_stats
    stats["crawler_after_spu_count"] = len(valid_items)

    crawler_url_set: set[str] = set()
    url_to_meta: dict[str, dict[str, str]] = {}
    by_platform: dict[str, dict[str, int]] = {}

    for item in valid_items:
        norm = normalize_url(item.get("url", ""))
        if not norm:
            continue
        crawler_url_set.add(norm)
        url_to_meta[norm] = item
        plat = str(item.get("platform") or "unknown").lower()
        bucket = by_platform.setdefault(plat, {"crawler_valid": 0, "matched": 0})
        bucket["crawler_valid"] += 1

    stats["crawler_unique_urls"] = len(crawler_url_set)
    if not crawler_url_set:
        warnings.append("kr4_5: no crawler URLs after SPU filter (denominator=0)")
        return None, issues, stats, warnings

    matched_urls = crawler_url_set & report_urls
    stats["matched_count"] = len(matched_urls)
    stats["extra_in_report_count"] = len(report_urls - crawler_url_set)

    for norm in matched_urls:
        plat = str(url_to_meta.get(norm, {}).get("platform") or "unknown").lower()
        by_platform.setdefault(plat, {"crawler_valid": 0, "matched": 0})
        by_platform[plat]["matched"] = by_platform[plat].get("matched", 0) + 1

    stats["by_platform"] = by_platform
    completeness = len(matched_urls) / len(crawler_url_set)
    stats["completeness"] = completeness

    missing = crawler_url_set - report_urls
    for norm in sorted(missing)[:KR4_5_ISSUES_MAX]:
        meta = url_to_meta.get(norm, {})
        issues.append({
            "url": meta.get("url", norm)[:200],
            "platform": meta.get("platform", ""),
            "product_name": (meta.get("product_name") or "")[:200],
            "product_model": meta.get("product_model", ""),
            "reason": "missing_in_report",
        })

    return completeness, issues, stats, warnings
