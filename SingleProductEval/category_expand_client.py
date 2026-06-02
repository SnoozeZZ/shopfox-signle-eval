"""
Category expand crawler client for KR4-5 (Top3 link completeness).
Separate from KR3-11 price crawler (crawler_client.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .config import (
    KR4_5_CACHE_DIR,
    KR4_5_CRAWLER_API_DEFAULT,
    KR4_5_CRAWLER_MAX_RETRIES,
    KR4_5_CRAWLER_RETRY_BACKOFF_SEC,
    KR4_5_CRAWLER_TIMEOUT_SEC_DEFAULT,
    KR4_5_USE_CRAWLER_CACHE,
    KR4_5_USE_FIXTURE_FALLBACK,
)
from .env import load_env

load_env()

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "category_expand_sample.json"
# Bump when parse schema changes so old empty-parse caches are not reused.
_CACHE_KEY_SUFFIX = "v2"

_ROOT_META_KEYS = frozenset({
    "status",
    "elapsed_ms",
    "total_tasks",
    "success",
    "errors",
    "keywords",
    "platforms",
    "message",
    "msg",
    "code",
    "error",
})


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    return float(val)


def get_category_expand_url() -> str:
    return os.getenv("CRAWLER_API", KR4_5_CRAWLER_API_DEFAULT).strip()


def get_category_expand_timeout() -> float:
    return _env_float("CRAWLER_TIMEOUT", KR4_5_CRAWLER_TIMEOUT_SEC_DEFAULT)


def _build_cache_key(cache_key: str | None, keywords: list[str], platforms: list[str]) -> str:
    base = cache_key or "|".join(keywords) + "|" + "|".join(platforms)
    return f"{base}|{_CACHE_KEY_SUFFIX}"


def _cache_path(cache_key: str) -> Path:
    safe = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return KR4_5_CACHE_DIR / f"{safe}.json"


def _load_cache(cache_key: str) -> Any | None:
    if not KR4_5_USE_CRAWLER_CACHE:
        return None
    path = _cache_path(cache_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(cache_key: str, payload: Any) -> None:
    if not KR4_5_USE_CRAWLER_CACHE:
        return
    KR4_5_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_key)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_str(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        val = item.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _clean_brand_text(text: str) -> str:
    return re.sub(r'["\'/>]+$', "", str(text or "").strip()).strip()


def _derive_product_model(raw: dict) -> str:
    style = _first_str(raw, ("Style", "style"))
    brand = _clean_brand_text(_first_str(raw, ("Brand", "brand")))
    spu = _first_str(raw, ("SPU ID", "SKU ID", "product_model", "model", "sku"))
    if style and brand:
        return f"{brand} {style}".strip()
    if style:
        return style
    if brand:
        return brand
    return spu


def normalize_crawler_item(raw: dict, platform_hint: str = "") -> dict[str, str] | None:
    """Map API row to {url, product_model, product_name, platform, brand}."""
    if not isinstance(raw, dict):
        return None
    url = _first_str(
        raw,
        ("Item URL", "url", "link", "product_url", "productLink", "product_link"),
    )
    if not url:
        return None
    platform = (
        platform_hint
        or _first_str(raw, ("platform", "sourcePlatform", "source", "site", "retailer"))
    ).lower()
    brand = _clean_brand_text(_first_str(raw, ("Brand", "brand")))
    return {
        "url": url,
        "product_model": _derive_product_model(raw),
        "product_name": _first_str(
            raw, ("Title", "product_name", "title", "name", "product_title")
        ),
        "platform": platform,
        "brand": brand,
    }


def _flatten_category_expand_data(payload: Any) -> list[tuple[dict, str]]:
    """
    Real API shape: data.{platform}.success.{keyword} -> [items].
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    rows: list[tuple[dict, str]] = []
    for platform_key, platform_body in data.items():
        if not isinstance(platform_body, dict):
            continue
        platform_hint = str(platform_key).strip().lower()
        success_block = platform_body.get("success")
        if not isinstance(success_block, dict):
            continue
        for _keyword, items in success_block.items():
            if not isinstance(items, list):
                continue
            for entry in items:
                if isinstance(entry, dict):
                    rows.append((entry, platform_hint))
    return rows


def _flatten_payload_legacy(payload: Any) -> list[tuple[dict, str]]:
    """Fallback for flat/list response shapes."""
    rows: list[tuple[dict, str]] = []

    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                rows.append((entry, _first_str(entry, ("platform", "source", "site"))))
        return rows

    if not isinstance(payload, dict):
        return rows

    for key in ("data", "results", "items", "products"):
        if key in payload:
            nested = _flatten_payload_legacy(payload[key])
            if nested:
                return nested

    for key, val in payload.items():
        if key.lower() in _ROOT_META_KEYS:
            continue
        if isinstance(val, list):
            for entry in val:
                if isinstance(entry, dict):
                    rows.append((entry, str(key)))
        elif isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, list):
                    for entry in sub_val:
                        if isinstance(entry, dict):
                            rows.append((entry, str(sub_key)))

    return rows


def _flatten_payload(payload: Any) -> list[tuple[dict, str]]:
    rows = _flatten_category_expand_data(payload)
    if rows:
        return rows
    return _flatten_payload_legacy(payload)


def parse_expand_response(payload: Any) -> list[dict[str, str]]:
    """Parse API JSON into normalized crawler items."""
    items: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for raw, platform_hint in _flatten_payload(payload):
        norm = normalize_crawler_item(raw, platform_hint)
        if not norm:
            continue
        url_key = norm["url"].lower()
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        items.append(norm)

    return items


def _load_fixture() -> Any:
    if _FIXTURE_PATH.exists():
        return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return {"data": {}}


def _post_expand(
    keywords: list[str],
    platforms: list[str],
    timeout: float,
) -> Any:
    url = get_category_expand_url()
    body = {"keywords": keywords, "platforms": platforms}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()


def expand_category(
    keywords: list[str],
    platforms: list[str],
    *,
    cache_key: str | None = None,
    use_fixture_on_failure: bool | None = None,
) -> tuple[list[dict[str, str]], str]:
    """
    Call category/expand and return normalized items.
    Returns (items, source) where source is cache|http|fixture.
    """
    key = _build_cache_key(cache_key, keywords, platforms)
    cached = _load_cache(key)
    if cached is not None:
        cached_items = parse_expand_response(cached)
        if cached_items:
            return cached_items, "cache"
        if (
            KR4_5_USE_FIXTURE_FALLBACK
            if use_fixture_on_failure is None
            else use_fixture_on_failure
        ):
            return parse_expand_response(_load_fixture()), "fixture"

    timeout = get_category_expand_timeout()
    fallback = (
        KR4_5_USE_FIXTURE_FALLBACK
        if use_fixture_on_failure is None
        else use_fixture_on_failure
    )
    last_error: Exception | None = None
    max_attempts = KR4_5_CRAWLER_MAX_RETRIES + 1

    for attempt in range(max_attempts):
        try:
            payload = _post_expand(keywords, platforms, timeout)
            items = parse_expand_response(payload)
            if items:
                _save_cache(key, payload)
                return items, "http"
            if fallback:
                fixture = _load_fixture()
                return parse_expand_response(fixture), "fixture"
            _save_cache(key, payload)
            return [], "http"
        except Exception as exc:
            last_error = exc
            if attempt >= KR4_5_CRAWLER_MAX_RETRIES:
                break
            time.sleep(KR4_5_CRAWLER_RETRY_BACKOFF_SEC * (2**attempt))

    if fallback:
        fixture = _load_fixture()
        return parse_expand_response(fixture), "fixture"

    if last_error is not None:
        raise last_error
    raise RuntimeError("category expand failed")
