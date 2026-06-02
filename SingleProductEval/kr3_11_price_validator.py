"""
KR3-11 validators: offer recorded price vs crawled live price.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .config import KR3_11_PRICE_TOLERANCE_ABS, KR3_11_USE_CRAWLER
from .crawler_client import (
    CrawlPriceResult,
    ParsedPrice,
    crawl_prices,
    format_price_display,
)


def _is_valid_http_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _round4(value: float) -> float:
    return round(float(value), 4)


def _recorded_price(offer: dict) -> float | None:
    price = offer.get("price")
    if price is None:
        return None
    try:
        return float(price)
    except (TypeError, ValueError):
        return None


def prices_match(
    recorded: float,
    parsed: ParsedPrice,
    tolerance_abs: float = 0.0,
) -> tuple[bool, str]:
    """
    Returns (matched, reason_if_not).
    reason: price_mismatch | price_out_of_range
    """
    rec = _round4(recorded)
    tol = max(0.0, tolerance_abs)

    if isinstance(parsed, tuple):
        low, high = _round4(parsed[0]), _round4(parsed[1])
        if low - tol <= rec <= high + tol:
            return True, ""
        return False, "price_out_of_range"

    crawled = _round4(parsed)
    if abs(rec - crawled) <= tol:
        return True, ""
    return False, "price_mismatch"


def _make_issue(
    index: int,
    offer: dict,
    recorded: float,
    crawl: CrawlPriceResult,
    reason: str,
) -> dict:
    return {
        "index": index,
        "retailer": str(offer.get("retailer") or ""),
        "url": str(offer.get("url") or "")[:200],
        "recorded_price": recorded,
        "crawled_price": format_price_display(crawl.parsed, crawl.price_raw),
        "reason": reason,
        "section": "priceComparison",
        "detail": crawl.error,
    }


def validate_offer_prices(
    offers: list[dict],
    *,
    crawl_enabled: bool | None = None,
) -> tuple[float | None, list[dict], dict[str, Any], list[str]]:
    """
    Returns (accuracy, issues, stats, warnings).
    """
    warnings: list[str] = []
    stats: dict[str, Any] = {
        "filtered_total": len(offers) if offers else 0,
        "evaluable": 0,
        "excluded_no_url": 0,
        "excluded_crawl_failed": 0,
        "matched": 0,
        "mismatched": 0,
    }

    if not offers:
        return None, [], stats, warnings

    use_crawler = KR3_11_USE_CRAWLER if crawl_enabled is None else crawl_enabled
    if not use_crawler:
        warnings.append("kr3_11: crawler disabled; accuracy not computed")
        return None, [], stats, warnings

    url_by_index: dict[int, str] = {}
    for i, offer in enumerate(offers):
        url = str(offer.get("url") or "").strip()
        if not _is_valid_http_url(url):
            stats["excluded_no_url"] += 1
            continue
        url_by_index[i] = url

    if not url_by_index:
        warnings.append("kr3_11: no offers with valid URLs; accuracy not computed")
        return None, [], stats, warnings

    unique_urls = list(dict.fromkeys(url_by_index.values()))
    try:
        crawl_results = crawl_prices(unique_urls)
    except Exception as exc:
        warnings.append(f"kr3_11: crawler unavailable: {exc}")
        return None, [], stats, warnings

    issues: list[dict] = []
    matched = 0
    mismatched = 0
    evaluable = 0

    for i, offer in enumerate(offers):
        url = url_by_index.get(i)
        if not url:
            continue

        crawl = crawl_results.get(url) or CrawlPriceResult(error="not_crawled")
        if crawl.parsed is None:
            stats["excluded_crawl_failed"] += 1
            continue

        recorded = _recorded_price(offer)
        if recorded is None:
            stats["excluded_crawl_failed"] += 1
            continue

        evaluable += 1
        ok, reason = prices_match(
            recorded, crawl.parsed, tolerance_abs=KR3_11_PRICE_TOLERANCE_ABS
        )
        if ok:
            matched += 1
        else:
            mismatched += 1
            issues.append(_make_issue(i, offer, recorded, crawl, reason))

    stats["evaluable"] = evaluable
    stats["matched"] = matched
    stats["mismatched"] = mismatched

    if stats["excluded_no_url"]:
        warnings.append(
            f"kr3_11: {stats['excluded_no_url']} offers excluded (no valid url)"
        )
    if stats["excluded_crawl_failed"]:
        warnings.append(
            f"kr3_11: {stats['excluded_crawl_failed']} offers excluded (crawl failed)"
        )

    if evaluable == 0:
        warnings.append("kr3_11: no evaluable offers; accuracy not computed")
        return None, issues, stats, warnings

    accuracy = matched / evaluable
    return accuracy, issues, stats, warnings
