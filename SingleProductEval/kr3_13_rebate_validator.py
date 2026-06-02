"""
KR3-13 validators: rebate/cashback section accuracy (platform dimension).
Uses embedded page text first, then httpx (no e-commerce crawler API).
"""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import (
    KR3_13_DESC_MIN_TOKEN_OVERLAP,
    KR3_13_HTTP_MAX_WORKERS,
    KR3_13_HTTP_TIMEOUT_SEC,
    KR3_13_LLM_BATCH_SIZE,
    KR3_13_MIN_PAGE_TEXT_LEN,
    KR3_13_RATE_TOLERANCE_PCT,
    KR3_13_SUPPORTED_SOURCES,
    KR3_13_SUPPORTED_TYPES,
    KR3_13_USE_LLM,
    KR3_13_VALIDATE_HTTP,
)
from .kr3_13_rebate_llm import (
    build_claim_payload,
    chunk_claims,
    compress_page_for_llm,
    llm_judge_url_batch,
    page_context_sufficient,
)
from .llm_client import has_dashscope_api_key

Outcome = str  # "correct" | "incorrect" | "unverifiable"

_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_SOURCE_HOSTS: dict[str, tuple[str, ...]] = {
    "rakuten": ("rakuten.com",),
    "befrugal": ("befrugal.com",),
    "topcashback": ("topcashback.com",),
    "rebatesme": ("rebatesme.com",),
    "shopathome": ("shopathome.com",),
    "mr rebates": ("mrrebates.com", "mr-rebates.com"),
    "swagbucks": ("swagbucks.com",),
    "upside": ("upside.com",),
}

_RETAILER_SLUGS: dict[str, tuple[str, ...]] = {
    "best buy": ("bestbuy", "best-buy"),
    "walmart": ("walmart",),
    "amazon": ("amazon",),
    "newegg": ("newegg",),
    "target": ("target",),
    "lowe's": ("lowes", "lowe's"),
    "lowes": ("lowes",),
    "ebay": ("ebay",),
}


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _normalize_source(source: str) -> str:
    s = str(source or "").strip().lower()
    s = s.replace(".", "")
    return _WS_RE.sub(" ", s).strip()


def _is_valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _html_to_text(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_rate_pct(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _PCT_RE.search(str(value))
    if m:
        return float(m.group(1))
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return None


def _rate_in_description(description: str) -> float | None:
    return _parse_rate_pct(description)


def _substantive_tokens(text: str, min_len: int = 4) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {w for w in words if len(w) >= min_len}


def _token_overlap(a: str, b: str, min_overlap: int) -> bool:
    ta = _substantive_tokens(a)
    tb = _substantive_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) >= min_overlap


def _categories_fuzzy_match(claimed: str, found: str) -> bool:
    c = _normalize_key(claimed)
    f = _normalize_key(found)
    if not c or not f:
        return False
    return c in f or f in c


def _source_supported(source: str) -> bool:
    norm = _normalize_source(source)
    return norm in KR3_13_SUPPORTED_SOURCES


def _source_matches_host(source: str, url: str) -> bool:
    norm = _normalize_source(source)
    hosts = _SOURCE_HOSTS.get(norm)
    if not hosts:
        return True
    try:
        host = (urlparse(url.strip()).netloc or "").lower()
    except Exception:
        return False
    return any(h in host for h in hosts)


def _retailer_matches_url(retailer: str, url: str) -> bool:
    rnorm = str(retailer or "").strip().lower()
    if not rnorm:
        return True
    pq = (urlparse(url.strip()).path + "?" + urlparse(url.strip()).query).lower()
    for key, slugs in _RETAILER_SLUGS.items():
        if key in rnorm or rnorm in key:
            return any(s in pq for s in slugs)
    bare = _normalize_key(retailer)
    return bare in _normalize_key(pq)


def _extract_claim(item: dict) -> dict[str, Any]:
    category_rates = item.get("categoryRates") or []
    first_cr = category_rates[0] if category_rates else {}
    category = (
        str(item.get("condition") or "").strip()
        or str(first_cr.get("category") or "").strip()
    )
    rate_pct = _parse_rate_pct(first_cr.get("rate"))
    if rate_pct is None:
        rate_pct = _parse_rate_pct(item.get("amount"))
    description = str(item.get("description") or "")
    up_to = "up to" in description.lower() or "upto" in description.lower()
    return {
        "category": category,
        "rate_pct": rate_pct,
        "description": description,
        "excluded_items": str(item.get("excludedItems") or ""),
        "up_to": up_to,
    }


def _field_consistency(item: dict, claim: dict[str, Any]) -> str | None:
    desc_rate = _rate_in_description(claim["description"])
    amount = item.get("amount")
    if desc_rate is not None and amount is not None:
        try:
            if abs(desc_rate - float(amount)) > KR3_13_RATE_TOLERANCE_PCT:
                return "field_inconsistent"
        except (TypeError, ValueError):
            pass
    category_rates = item.get("categoryRates") or []
    if category_rates:
        cr_cat = str(category_rates[0].get("category") or "").strip()
        cond = str(item.get("condition") or "").strip()
        if cr_cat and cond and not _categories_fuzzy_match(cr_cat, cond):
            return "field_inconsistent"
    return None


def _snippet_around_category(page_text: str, category: str, radius: int = 200) -> str:
    lower = page_text.lower()
    needle = category.lower()
    idx = lower.find(needle)
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(page_text), idx + len(category) + radius)
    return page_text[start:end].strip()


def _rate_near_category(page_text: str, category: str) -> float | None:
    snippet = _snippet_around_category(page_text, category, radius=250)
    if not snippet:
        return None
    m = _PCT_RE.search(snippet)
    return float(m.group(1)) if m else None


def _category_on_page(page_text: str, category: str) -> bool:
    cat = str(category or "").strip()
    if len(cat) < 8:
        return False
    pattern = re.escape(cat).replace(r"\ ", r"\s+")
    if re.search(pattern, page_text, re.I):
        return True
    return _categories_fuzzy_match(cat, page_text[:8000])


def extract_rebate_tiers(page_text: str, hint_categories: list[str] | None = None) -> list[dict[str, Any]]:
    """Extract category/rate tiers from plain page text."""
    if not page_text or len(page_text) < 20:
        return []

    hints = list(dict.fromkeys(h for h in (hint_categories or []) if h))
    tiers: list[dict[str, Any]] = []
    seen: set[str] = set()

    for m in _PCT_RE.finditer(page_text):
        rate = float(m.group(1))
        start = max(0, m.start() - 120)
        end = min(len(page_text), m.end() + 120)
        snippet = page_text[start:end].strip()

        category = ""
        for hint in hints:
            if hint and hint.lower() in snippet.lower():
                category = hint
                break

        if not category:
            before = page_text[max(0, m.start() - 80): m.start()]
            cap = re.findall(r"([A-Z][A-Za-z0-9&',.\-\s]{3,60})", before)
            if cap:
                category = cap[-1].strip()

        cat_key = _normalize_key(category or f"rate_{rate}")
        if cat_key in seen:
            continue
        seen.add(cat_key)
        tiers.append({
            "category": category or f"rate_{rate}",
            "rate_pct": rate,
            "snippet": snippet,
        })

    for hint in hints:
        if not _category_on_page(page_text, hint):
            continue
        cat_key = _normalize_key(hint)
        if cat_key in seen:
            continue
        seen.add(cat_key)
        snippet = _snippet_around_category(page_text, hint)
        tiers.append({
            "category": hint,
            "rate_pct": _rate_near_category(page_text, hint),
            "snippet": snippet,
        })

    return tiers


def _fetch_url_text(url: str, timeout: float) -> tuple[str | None, str | None]:
    """Returns (text, error_reason)."""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url)
            status = resp.status_code
            if status in (403, 429):
                return None, "http_blocked"
            if status in (404, 410) or status >= 500:
                return None, "http_dead"
            if status >= 400:
                return None, "http_error"
            text = _html_to_text(resp.text)
            if len(text) < KR3_13_MIN_PAGE_TEXT_LEN:
                return None, "page_too_short"
            return text, None
    except httpx.TimeoutException:
        return None, "timeout"
    except Exception as exc:
        return None, f"fetch_error:{str(exc)[:80]}"


def _entry_text_blob(item: dict) -> str:
    parts = [
        str(item.get("excludedItems") or ""),
        str(item.get("description") or ""),
        str(item.get("cashbackPostTime") or ""),
        str(item.get("cashbackPayoutTime") or ""),
        str(item.get("withdrawalMethod") or ""),
    ]
    return "\n".join(p.strip() for p in parts if p and str(p).strip())


def _build_embedded_text_by_url(items: list[dict]) -> dict[str, str]:
    by_url: dict[str, list[str]] = {}
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        blob = _entry_text_blob(item)
        if blob:
            by_url.setdefault(url, []).append(blob)
    return {url: "\n".join(parts) for url, parts in by_url.items()}


def _embedded_covers_hints(embedded: str, hint_categories: list[str]) -> bool:
    if not embedded or len(embedded) < KR3_13_MIN_PAGE_TEXT_LEN:
        return False
    return any(h and _category_on_page(embedded, h) for h in hint_categories)


def _resolve_page_text(
    url: str,
    embedded_by_url: dict[str, str],
    http_cache: dict[str, tuple[str | None, str | None]],
    validate_http: bool,
    hint_categories: list[str] | None = None,
) -> tuple[str | None, str]:
    hints = hint_categories or []
    embedded = embedded_by_url.get(url, "")
    if _embedded_covers_hints(embedded, hints):
        return embedded, "embedded"

    if url in http_cache:
        text, err = http_cache[url]
        return (text, "http") if text else (None, err or "http_failed")

    if validate_http and KR3_13_VALIDATE_HTTP:
        text, err = _fetch_url_text(url, KR3_13_HTTP_TIMEOUT_SEC)
        http_cache[url] = (text, err)
        return (text, "http") if text else (None, err or "http_failed")

    if len(embedded) >= KR3_13_MIN_PAGE_TEXT_LEN:
        return embedded, "embedded_fallback"
    if embedded:
        return embedded, "embedded_short"
    return None, "no_page_text"


def _match_tier(
    claim: dict[str, Any],
    tiers: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    category = claim["category"]
    if not tiers:
        return None, "no_tiers"

    scored: list[tuple[int, dict[str, Any]]] = []
    for t in tiers:
        if category and _categories_fuzzy_match(category, t["category"]):
            scored.append((3, t))
        elif category and category.lower() in (t.get("snippet") or "").lower():
            scored.append((2, t))
        elif not category:
            scored.append((1, t))

    if not scored:
        return None, "tier_not_found"

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0]
    best = [t for s, t in scored if s == best_score]
    if len(best) > 1:
        return None, "ambiguous_match"
    return best[0], None


def _verify_matched_tier(
    item: dict,
    claim: dict[str, Any],
    tier: dict[str, Any],
) -> str | None:
    claimed_rate = claim["rate_pct"]
    found_rate = tier.get("rate_pct")
    if claimed_rate is not None and found_rate is not None:
        tol = KR3_13_RATE_TOLERANCE_PCT
        if claim["up_to"]:
            if claimed_rate > found_rate + tol:
                return "rate_mismatch"
        elif abs(claimed_rate - found_rate) > tol:
            return "rate_mismatch"

    desc_blob = " ".join(
        [
            claim["description"],
            claim["excluded_items"],
            str(item.get("retailer") or ""),
            str(item.get("source") or ""),
            claim["category"],
        ]
    )
    snippet_blob = tier.get("snippet") or ""
    if claim["category"] and not _categories_fuzzy_match(claim["category"], tier["category"]):
        if claim["category"].lower() not in snippet_blob.lower():
            return "category_mismatch"

    if snippet_blob:
        if not _token_overlap(desc_blob, snippet_blob, KR3_13_DESC_MIN_TOKEN_OVERLAP):
            if claim["category"] and claim["category"].lower() not in snippet_blob.lower():
                return "description_mismatch"
    elif claim["category"]:
        ex = claim.get("excluded_items") or ""
        if not _category_on_page(ex, claim["category"]) and not _token_overlap(
            desc_blob, claim["category"], 1
        ):
            return "description_mismatch"

    retailer = str(item.get("retailer") or "").lower()
    source_key = _normalize_source(str(item.get("source") or ""))
    desc_key = _normalize_key(claim["description"])
    if retailer and _normalize_key(retailer) not in desc_key:
        return "description_mismatch"
    if source_key and source_key not in desc_key:
        return "description_mismatch"

    return None


def _make_issue(
    index: int,
    item: dict,
    claim: dict[str, Any],
    reason: str,
    **extra: Any,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "index": index,
        "retailer": str(item.get("retailer") or ""),
        "source": str(item.get("source") or ""),
        "url": str(item.get("url") or "")[:200],
        "category": claim.get("category"),
        "claimed_rate": claim.get("rate_pct"),
        "reason": reason,
        "section": "priceComparison.rebatesAndCoupons",
    }
    issue.update(extra)
    return issue


def _get_rebate_items(report: dict) -> list[dict]:
    pc = report.get("priceComparison") or {}
    items = pc.get("rebatesAndCoupons")
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def _judge_single_rebate_rules(
    item: dict,
    claim: dict[str, Any],
    page_text: str | None,
    tiers: list[dict[str, Any]] | None,
    hint_categories: list[str],
) -> tuple[Outcome, str, dict[str, Any]]:
    """
    v1 tier-based verdict. Returns (outcome, reason, issue_extra).
    outcome: correct | incorrect | unverifiable
    """
    extra: dict[str, Any] = {"match_method": "rule"}

    if not page_text or len(page_text) < KR3_13_MIN_PAGE_TEXT_LEN:
        return "unverifiable", "no_page_text", extra

    tier_list = tiers if tiers is not None else extract_rebate_tiers(page_text, hint_categories)
    if not tier_list:
        return "unverifiable", "no_tiers_parsed", extra

    tier, match_err = _match_tier(claim, tier_list)
    if match_err == "ambiguous_match":
        return "unverifiable", match_err, extra
    if tier is None:
        extra["tiers_on_page"] = len(tier_list)
        return "incorrect", "tier_not_found", extra

    verify_err = _verify_matched_tier(item, claim, tier)
    if verify_err:
        extra["found_rate"] = tier.get("rate_pct")
        extra["matched_category"] = tier.get("category")
        return "incorrect", verify_err, extra

    return "correct", "", extra


def _record_verdict(
    stats: dict[str, int],
    issues: list[dict],
    index: int,
    item: dict,
    claim: dict[str, Any],
    outcome: Outcome,
    reason: str,
    issue_extra: dict[str, Any] | None = None,
) -> None:
    extra = dict(issue_extra or {})
    match_method = extra.pop("match_method", "rule")

    if outcome == "unverifiable":
        stats["unverifiable"] += 1
        if reason:
            issues.append(_make_issue(index, item, claim, reason, match_method=match_method, **extra))
        return

    stats["attempted"] += 1
    if match_method == "llm":
        stats["llm_judged"] += 1
    else:
        stats["rule_judged"] += 1

    if outcome == "correct":
        stats["correct"] += 1
        return

    stats["incorrect"] += 1
    issues.append(
        _make_issue(index, item, claim, reason, match_method=match_method, **extra)
    )


def validate_rebate_info(
    report: dict,
    gt: dict,
    *,
    validate_http: bool | None = None,
) -> tuple[float | None, list[dict], dict[str, int], list[str]]:
    """Returns (accuracy, issues, stats, warnings)."""
    del gt  # reserved for future relevance filters
    if validate_http is None:
        validate_http = KR3_13_VALIDATE_HTTP

    items = _get_rebate_items(report)
    stats: dict[str, int] = {
        "raw_count": len(items),
        "eligible_count": 0,
        "attempted": 0,
        "correct": 0,
        "incorrect": 0,
        "unverifiable": 0,
        "excluded_raw": 0,
        "unique_urls": 0,
        "unique_urls_fetched": 0,
        "llm_judged": 0,
        "rule_judged": 0,
        "llm_unverifiable": 0,
    }
    issues: list[dict] = []
    warnings: list[str] = []

    if not items:
        return None, [], stats, warnings

    eligible_indices: list[int] = []
    for i, item in enumerate(items):
        url = str(item.get("url") or "").strip()
        rtype = str(item.get("type") or "cashback").strip().lower()
        source = str(item.get("source") or "")
        if not _is_valid_http_url(url):
            stats["excluded_raw"] += 1
            continue
        if rtype not in KR3_13_SUPPORTED_TYPES:
            stats["excluded_raw"] += 1
            continue
        if not _source_supported(source):
            stats["unverifiable"] += 1
            continue
        eligible_indices.append(i)

    stats["eligible_count"] = len(eligible_indices)
    if not eligible_indices:
        return None, issues, stats, warnings

    eligible_items = [items[i] for i in eligible_indices]
    embedded_by_url = _build_embedded_text_by_url(eligible_items)
    unique_urls = sorted({str(items[i].get("url") or "").strip() for i in eligible_indices})
    stats["unique_urls"] = len(unique_urls)

    hint_categories = []
    for item in eligible_items:
        c = _extract_claim(item)["category"]
        if c:
            hint_categories.append(c)

    http_cache: dict[str, tuple[str | None, str | None]] = {}
    urls_needing_http = [
        u
        for u in unique_urls
        if not _embedded_covers_hints(embedded_by_url.get(u, ""), hint_categories)
    ]
    if validate_http and urls_needing_http:
        with ThreadPoolExecutor(max_workers=KR3_13_HTTP_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_url_text, u, KR3_13_HTTP_TIMEOUT_SEC): u for u in urls_needing_http}
            for fut in as_completed(futures):
                url = futures[fut]
                try:
                    text, err = fut.result()
                    http_cache[url] = (text, err)
                    if text:
                        stats["unique_urls_fetched"] += 1
                except Exception as exc:
                    http_cache[url] = (None, f"fetch_error:{str(exc)[:80]}")

    page_text_by_url: dict[str, str] = {}
    tiers_by_url: dict[str, list[dict[str, Any]]] = {}
    for url in unique_urls:
        page_text, _src = _resolve_page_text(
            url, embedded_by_url, http_cache, validate_http, hint_categories
        )
        if page_text:
            page_text_by_url[url] = page_text
            tiers_by_url[url] = extract_rebate_tiers(page_text, hint_categories)

    use_llm = KR3_13_USE_LLM and has_dashscope_api_key()
    if not use_llm:
        warnings.append("kr3_13: LLM disabled or unavailable, using rule fallback")

    pending_by_url: dict[str, list[tuple[int, dict, dict[str, Any]]]] = {}

    for i in eligible_indices:
        item = items[i]
        url = str(item.get("url") or "").strip()
        claim = _extract_claim(item)

        if not _source_matches_host(str(item.get("source") or ""), url):
            _record_verdict(
                stats, issues, i, item, claim, "incorrect", "link_source_host_mismatch",
                {"match_method": "rule"},
            )
            continue

        if not _retailer_matches_url(str(item.get("retailer") or ""), url):
            _record_verdict(
                stats, issues, i, item, claim, "incorrect", "link_retailer_mismatch",
                {"match_method": "rule"},
            )
            continue

        field_err = _field_consistency(item, claim)
        if field_err:
            _record_verdict(
                stats, issues, i, item, claim, "incorrect", field_err,
                {"match_method": "rule"},
            )
            continue

        pending_by_url.setdefault(url, []).append((i, item, claim))

    def _rule_fallback(
        index: int,
        item: dict,
        claim: dict[str, Any],
        url: str,
    ) -> None:
        page_text = page_text_by_url.get(url)
        tiers = tiers_by_url.get(url)
        outcome, reason, extra = _judge_single_rebate_rules(
            item, claim, page_text, tiers, hint_categories
        )
        _record_verdict(stats, issues, index, item, claim, outcome, reason, extra)

    for url, group in pending_by_url.items():
        page_text = page_text_by_url.get(url)
        if not page_text or len(page_text) < KR3_13_MIN_PAGE_TEXT_LEN:
            for i, item, claim in group:
                _record_verdict(stats, issues, i, item, claim, "unverifiable", "no_page_text")
            continue

        compressed = compress_page_for_llm(page_text, hint_categories)
        if not page_context_sufficient(compressed):
            for i, item, claim in group:
                _record_verdict(
                    stats, issues, i, item, claim, "unverifiable", "page_context_insufficient"
                )
            continue

        if not use_llm:
            for i, item, claim in group:
                _rule_fallback(i, item, claim, url)
            continue

        retailer = str(group[0][1].get("retailer") or "")
        source = str(group[0][1].get("source") or "")
        payloads = [build_claim_payload(i, item, claim) for i, item, claim in group]
        index_to_row = {i: (item, claim) for i, item, claim in group}
        llm_handled: set[int] = set()

        for batch in chunk_claims(payloads, KR3_13_LLM_BATCH_SIZE):
            try:
                llm_results = llm_judge_url_batch(url, compressed, retailer, source, batch)
            except Exception as exc:
                warnings.append(f"kr3_13: LLM batch failed: {str(exc)[:200]}")
                for payload in batch:
                    idx = int(payload["index"])
                    item, claim = index_to_row[idx]
                    _rule_fallback(idx, item, claim, url)
                    llm_handled.add(idx)
                continue

            for payload in batch:
                idx = int(payload["index"])
                llm_handled.add(idx)
                item, claim = index_to_row[idx]

                if idx not in llm_results:
                    _rule_fallback(idx, item, claim, url)
                    llm_handled.add(idx)
                    continue

                res = llm_results[idx]
                if not res.get("verifiable", True):
                    stats["llm_unverifiable"] += 1
                    _record_verdict(
                        stats,
                        issues,
                        idx,
                        item,
                        claim,
                        "unverifiable",
                        "llm_not_verifiable",
                        {
                            "match_method": "llm",
                            "llm_reason": res.get("reason", ""),
                        },
                    )
                    continue

                if res.get("match"):
                    _record_verdict(
                        stats,
                        issues,
                        idx,
                        item,
                        claim,
                        "correct",
                        "",
                        {"match_method": "llm", "llm_reason": res.get("reason", "")},
                    )
                else:
                    _record_verdict(
                        stats,
                        issues,
                        idx,
                        item,
                        claim,
                        "incorrect",
                        "llm_mismatch",
                        {
                            "match_method": "llm",
                            "llm_reason": res.get("reason", ""),
                        },
                    )

        for i, item, claim in group:
            if i not in llm_handled:
                _rule_fallback(i, item, claim, url)

    attempted = stats["attempted"]
    if attempted == 0:
        return None, issues, stats, warnings
    accuracy = stats["correct"] / attempted
    return accuracy, issues, stats, warnings
