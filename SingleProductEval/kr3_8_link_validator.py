"""
KR3-8 validators: offer link pointing accuracy in price-comparison section.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal
from urllib.parse import urlparse

import httpx

from .config import (
    KR3_8_HTTP_TIMEOUT_SEC,
    KR3_8_VALIDATE_HTTP,
    RETAILER_ALIASES,
)

UrlClass = Literal["detail", "listing", "unknown"]

_GENERIC_LISTING_PATTERNS = (
    r"/search",
    r"/browse",
    r"/sch/",
    r"/s\?",
    r"/s/",
    r"/deals/",
    r"/stores/",
    r"/click\.",
    r"/redirect",
)

_PLATFORM_DETAIL_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "amazon": (
        ("/dp/", "/gp/product/"),
        ("/s?", "/s/", "/b?", "/b/", "/stores/", "/deals/"),
    ),
    "ebay": (
        ("/itm/",),
        ("/sch/", "/b/"),
    ),
    "walmart": (
        ("/ip/",),
        ("/search/", "/browse/"),
    ),
    "best buy": (
        ("/product/",),
        ("/site/searchpage", "/site/offer"),
    ),
    "b&h photo": (
        ("/c/product/",),
        ("/c/search/", "/c/browse/"),
    ),
}


def _normalize_retailer(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    if key in RETAILER_ALIASES:
        return RETAILER_ALIASES[key].lower()
    bare = key.replace(".com", "").replace(".co.uk", "")
    if bare in RETAILER_ALIASES:
        return RETAILER_ALIASES[bare].lower()
    return key


def _retailer_key(retailer: str) -> str:
    normalized = _normalize_retailer(retailer)
    for key in _PLATFORM_DETAIL_RULES:
        if key in normalized or normalized in key:
            return key
    if "amazon" in normalized:
        return "amazon"
    if "ebay" in normalized:
        return "ebay"
    if "walmart" in normalized:
        return "walmart"
    if "best buy" in normalized or "bestbuy" in normalized:
        return "best buy"
    if "b&h" in normalized or "bhphoto" in normalized:
        return "b&h photo"
    return normalized


def _path_and_query(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        return (parsed.path or "") + ("?" + parsed.query if parsed.query else "")
    except Exception:
        return url.lower()


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(p in lower for p in patterns)


def classify_url(url: str, retailer: str) -> UrlClass:
    """Classify URL as detail page, listing page, or unknown."""
    if not url or not isinstance(url, str):
        return "listing"

    pq = _path_and_query(url)
    key = _retailer_key(retailer)

    if key in _PLATFORM_DETAIL_RULES:
        detail_patterns, listing_patterns = _PLATFORM_DETAIL_RULES[key]
        if _matches_any(pq, listing_patterns):
            return "listing"
        if _matches_any(pq, detail_patterns):
            return "detail"
        if key == "best buy" and "/site/" in pq.lower() and "sku" in pq.lower():
            return "detail"
        return "unknown"

    if any(re.search(p, pq, re.I) for p in _GENERIC_LISTING_PATTERNS):
        return "listing"

    try:
        path = urlparse(url.strip()).path or ""
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2:
            return "detail"
    except Exception:
        pass

    return "unknown"


def _is_valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _static_offer_correct(offer: dict) -> tuple[bool, str | None]:
    url = str(offer.get("url") or "").strip()
    retailer = str(offer.get("retailer") or "")

    if not _is_valid_http_url(url):
        return False, "missing_or_invalid_url"

    url_class = classify_url(url, retailer)
    if url_class == "listing":
        return False, "listing_page_url"
    if url_class == "unknown":
        return False, "url_class_unknown"

    pi = (offer.get("metadata") or {}).get("product_identity") or {}
    if pi.get("is_target_product") is False:
        return False, "not_target_product"

    return True, None


def _http_check_offer(
    index: int,
    offer: dict,
    static_correct: bool,
    validate_http: bool,
) -> tuple[int, bool, dict | None]:
    """Returns (index, final_correct, issue_or_none)."""
    url = str(offer.get("url") or "").strip()
    retailer = str(offer.get("retailer") or "")

    if not validate_http or not static_correct:
        return index, static_correct, None

    issue_base = {
        "index": index,
        "retailer": retailer,
        "url": url,
        "section": "priceComparison",
    }

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=KR3_8_HTTP_TIMEOUT_SEC,
        ) as client:
            resp = client.get(url)
            status = resp.status_code
            final_url = str(resp.url)

            if status in (403, 429):
                return index, static_correct, {
                    **issue_base,
                    "reason": "http_inconclusive",
                    "detail": f"HTTP {status}",
                }

            if status in (404, 410) or status >= 500:
                return index, False, {
                    **issue_base,
                    "reason": "dead_link",
                    "detail": f"HTTP {status}",
                }

            if status >= 400:
                return index, static_correct, {
                    **issue_base,
                    "reason": "http_inconclusive",
                    "detail": f"HTTP {status}",
                }

            final_class = classify_url(final_url, retailer)
            if final_class == "listing":
                return index, False, {
                    **issue_base,
                    "reason": "redirect_to_listing",
                    "detail": final_url[:200],
                }

            return index, static_correct, None

    except httpx.TimeoutException:
        return index, static_correct, {
            **issue_base,
            "reason": "http_inconclusive",
            "detail": "timeout",
        }
    except Exception as exc:
        return index, static_correct, {
            **issue_base,
            "reason": "http_inconclusive",
            "detail": str(exc)[:200],
        }


def offer_link_correctness(
    offers: list[dict],
    validate_http: bool | None = None,
) -> tuple[dict[int, bool], list[dict]]:
    """
    Per-offer link correctness for all offers.

    Returns (index -> correct, issues list). Empty offers -> ({}, []).
    """
    if not offers:
        return {}, []

    do_http = KR3_8_VALIDATE_HTTP if validate_http is None else validate_http
    issues: list[dict] = []
    static_results: list[tuple[int, bool, str | None]] = []

    for i, offer in enumerate(offers):
        correct, static_reason = _static_offer_correct(offer)
        static_results.append((i, correct, static_reason))
        if not correct and static_reason:
            issues.append({
                "index": i,
                "retailer": str(offer.get("retailer") or ""),
                "url": str(offer.get("url") or ""),
                "reason": static_reason,
                "section": "priceComparison",
            })

    final_correct = {i: c for i, c, _ in static_results}

    if do_http:
        http_targets = [
            (i, offer, static_results[i][1])
            for i, offer in enumerate(offers)
            if static_results[i][1]
        ]
        if http_targets:
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {
                    pool.submit(_http_check_offer, i, offer, sc, do_http): i
                    for i, offer, sc in http_targets
                }
                for fut in as_completed(futures):
                    idx, is_correct, http_issue = fut.result()
                    final_correct[idx] = is_correct
                    if http_issue:
                        issues.append(http_issue)
                    elif not is_correct:
                        offer = offers[idx]
                        issues.append({
                            "index": idx,
                            "retailer": str(offer.get("retailer") or ""),
                            "url": str(offer.get("url") or ""),
                            "reason": "dead_link",
                            "section": "priceComparison",
                        })

    return final_correct, issues


def validate_offer_links(
    offers: list[dict],
    validate_http: bool | None = None,
) -> tuple[float | None, list[dict]]:
    """
    Validate all offers for KR3-8 link pointing accuracy.

    Returns (accuracy 0~1 or None if no offers, issues list).
    """
    if not offers:
        return None, []

    final_correct, issues = offer_link_correctness(offers, validate_http=validate_http)
    correct_count = sum(1 for c in final_correct.values() if c)
    accuracy = correct_count / len(offers)
    return accuracy, issues
