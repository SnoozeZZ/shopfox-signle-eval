"""
KR3-1 validators: spec + price-comparison section structural checks.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import KR3_1_VALIDATE_IMAGE_HTTP, KR3_1_IMAGE_HTTP_TIMEOUT_SEC

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_GARBLED_PATTERNS = ("\ufffd", "â€", "Ã", "Ã©", "Ã¨")


def _normalize_option(val: Any) -> str:
    return str(val or "").strip().lower()


def _looks_garbled(text: str) -> bool:
    if not text:
        return False
    return any(p in text for p in _GARBLED_PATTERNS)


def _is_english(text: str) -> bool:
    if not text or not isinstance(text, str):
        return True
    return _CJK_RE.search(text) is None


def _is_valid_http_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _collect_spec_strings(report: dict) -> list[str]:
    strings: list[str] = []
    spu = report.get("spu_metadata") or {}
    vs = spu.get("variant_schema") or {}

    for field in ("product_name", "product_model", "product_brand", "product_category"):
        val = spu.get(field)
        if val:
            strings.append(str(val))

    for dim, opts in vs.items():
        strings.append(str(dim))
        if isinstance(opts, list):
            strings.extend(str(o) for o in opts)

    default_sel = report.get("defaultSelection") or {}
    if isinstance(default_sel, dict):
        for k, v in default_sel.items():
            strings.append(str(k))
            strings.append(str(v))

    for sku in report.get("sku_combinations") or []:
        if not isinstance(sku, dict):
            continue
        if sku.get("display_name"):
            strings.append(str(sku["display_name"]))
        va = sku.get("variant_attributes") or {}
        if isinstance(va, dict):
            for k, v in va.items():
                strings.append(str(k))
                strings.append(str(v))

    for vg in report.get("variationGroups") or []:
        if not isinstance(vg, dict):
            continue
        if vg.get("label"):
            strings.append(str(vg["label"]))
        for opt in vg.get("options") or []:
            if isinstance(opt, dict) and opt.get("displayValue"):
                strings.append(str(opt["displayValue"]))

    return strings


def _validate_spec_section(report: dict) -> list[str]:
    failures: list[str] = []
    spu = report.get("spu_metadata") or {}
    vs = spu.get("variant_schema") or {}

    if not isinstance(vs, dict):
        failures.append("variant_schema missing or invalid")
        return failures

    for dim, opts in vs.items():
        if not isinstance(opts, list):
            failures.append(f"variant_schema.{dim} is not a list")
            continue
        normalized = [_normalize_option(o) for o in opts]
        if len(normalized) != len(set(normalized)):
            failures.append(f"duplicate values in variant_schema.{dim}")

    for text in _collect_spec_strings(report):
        if not _is_english(text):
            failures.append(f"non-English spec text: {text[:80]}")
            break
        if _looks_garbled(text):
            failures.append(f"garbled spec text: {text[:80]}")
            break

    images = report.get("images") or []
    if not isinstance(images, list) or len(images) < 1:
        failures.append("top-level images[] must have at least 1 entry")
    else:
        for i, url in enumerate(images):
            if not _is_valid_http_url(str(url)):
                failures.append(f"invalid image URL at images[{i}]")
                break

    return failures


def _validate_price_comparison_section(report: dict) -> list[str]:
    failures: list[str] = []
    pc = report.get("priceComparison")
    if not isinstance(pc, dict):
        failures.append("priceComparison missing or invalid")
        return failures

    offers = pc.get("offers") or []
    if not isinstance(offers, list):
        failures.append("priceComparison.offers is not a list")
        return failures

    for i, offer in enumerate(offers):
        if not isinstance(offer, dict):
            failures.append(f"offer[{i}] is not an object")
            continue
        for field in ("retailer", "product_name", "condition"):
            val = offer.get(field)
            if val is None:
                continue
            text = str(val)
            if not _is_english(text):
                failures.append(f"non-English offer[{i}].{field}: {text[:60]}")
                return failures
            if _looks_garbled(text):
                failures.append(f"garbled offer[{i}].{field}: {text[:60]}")
                return failures
        url = offer.get("url")
        if not url or not str(url).strip():
            failures.append(f"offer[{i}] missing url")
            return failures

    return failures


def _check_image_http(url: str) -> str | None:
    """Return issue message if image URL is not reachable, else None."""
    try:
        with httpx.Client(follow_redirects=True, timeout=KR3_1_IMAGE_HTTP_TIMEOUT_SEC) as client:
            resp = client.head(url)
            if resp.status_code >= 400:
                resp = client.get(url)
            if resp.status_code != 200:
                return f"image HTTP {resp.status_code}: {url[:120]}"
            content_type = resp.headers.get("content-type", "").lower()
            if content_type and "image/" not in content_type:
                return f"image Content-Type not image/* ({content_type}): {url[:120]}"
    except Exception as exc:
        return f"image unreachable ({exc}): {url[:120]}"
    return None


def _validate_images_http(report: dict) -> list[str]:
    warnings: list[str] = []
    if not KR3_1_VALIDATE_IMAGE_HTTP:
        return warnings

    images = report.get("images") or []
    if not isinstance(images, list):
        return warnings

    for url in images:
        if not _is_valid_http_url(str(url)):
            continue
        issue = _check_image_http(str(url).strip())
        if issue:
            warnings.append(issue)

    return warnings


def validate_key_info(
    report: dict,
    validate_images_http: bool | None = None,
) -> tuple[bool, list[str]]:
    """
    Validate KR3-1 spec + price-comparison sections.

    Returns (valid, issues) where issues includes blocking failures and
    non-blocking HTTP image warnings.
    """
    failures = _validate_spec_section(report)
    failures.extend(_validate_price_comparison_section(report))

    issues = list(failures)
    if validate_images_http if validate_images_http is not None else KR3_1_VALIDATE_IMAGE_HTTP:
        issues.extend(_validate_images_http(report))

    return len(failures) == 0, issues
