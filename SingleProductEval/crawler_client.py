"""
Price crawler client for KR3-11 (DashScope / AI crawl price API).
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Union

import httpx

from .env import load_env

load_env()

ParsedPrice = Union[float, tuple[float, float]]


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    return float(val)


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    return int(val)


def get_crawler_url() -> str:
    return os.getenv(
        "CRAWLER_URL",
        "http://47.251.122.154:8762/api/ai/crawl/price",
    ).strip()


def get_crawler_timeout() -> float:
    return _env_float("CRAWLER_REQUEST_TIMEOUT", 60.0)


def get_crawler_batch_size() -> int:
    return _env_int("CRAWLER_BATCH_SIZE", 31)


def get_crawler_max_in_flight() -> int:
    return _env_int("CRAWLER_MAX_IN_FLIGHT", 32)


def get_crawler_submit_interval() -> float:
    return _env_float("CRAWLER_SUBMIT_INTERVAL", 1.0)


def get_crawler_max_retries() -> int:
    return _env_int("CRAWLER_MAX_RETRIES", 3)


def get_crawler_retry_backoff() -> float:
    return _env_float("CRAWLER_RETRY_BACKOFF_SEC", 2.0)


@dataclass
class CrawlPriceResult:
    price_raw: str | None = None
    parsed: ParsedPrice | None = None
    error: str | None = None


def _is_invalid_price_value(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, (int, float)):
        return val == 0
    s = str(val).strip()
    return s in ("", "0", "0.0", "0.0000", "none", "null")


def parse_crawled_price(item: dict[str, Any]) -> CrawlPriceResult:
    """Parse one API data item into CrawlPriceResult."""
    price_raw = item.get("price")
    if price_raw is not None and not isinstance(price_raw, str):
        price_raw = str(price_raw)

    min_p = item.get("min_price")
    max_p = item.get("max_price")
    if min_p is not None and max_p is not None:
        try:
            low = float(min_p)
            high = float(max_p)
            if low > high:
                low, high = high, low
            raw = price_raw or f"{low:.4f}-{high:.4f}"
            return CrawlPriceResult(price_raw=raw, parsed=(low, high))
        except (TypeError, ValueError):
            pass

    if _is_invalid_price_value(price_raw):
        return CrawlPriceResult(price_raw=price_raw, error="invalid_price")

    text = str(price_raw).strip()
    range_match = re.match(
        r"^\s*([\d.]+)\s*-\s*([\d.]+)\s*$",
        text,
    )
    if range_match:
        try:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            if low > high:
                low, high = high, low
            return CrawlPriceResult(price_raw=text, parsed=(low, high))
        except ValueError:
            return CrawlPriceResult(price_raw=text, error="invalid_range")

    try:
        return CrawlPriceResult(price_raw=text, parsed=float(text))
    except ValueError:
        return CrawlPriceResult(price_raw=text, error="invalid_price")


def format_price_display(parsed: ParsedPrice | None, price_raw: str | None) -> str:
    if price_raw:
        return str(price_raw)
    if parsed is None:
        return ""
    if isinstance(parsed, tuple):
        return f"{parsed[0]:.4f}-{parsed[1]:.4f}"
    return f"{parsed:.4f}"


async def _post_batch(
    client: httpx.AsyncClient,
    url: str,
    urls: list[str],
    timeout: float,
) -> dict[str, CrawlPriceResult]:
    out: dict[str, CrawlPriceResult] = {u: CrawlPriceResult(error="request_failed") for u in urls}
    try:
        resp = await client.post(
            url,
            json={"urls": urls},
            timeout=timeout,
        )
        if resp.status_code != 200:
            err = f"HTTP {resp.status_code}"
            for u in urls:
                out[u] = CrawlPriceResult(error=err)
            return out

        body = resp.json()
        if not isinstance(body, dict):
            for u in urls:
                out[u] = CrawlPriceResult(error="invalid_response")
            return out

        data = body.get("data")
        if not isinstance(data, list):
            for u in urls:
                out[u] = CrawlPriceResult(error="missing_data")
            return out

        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            item_url = str(item.get("url") or "").strip()
            if not item_url or item_url not in out:
                continue
            seen.add(item_url)
            out[item_url] = parse_crawled_price(item)

        for u in urls:
            if u not in seen:
                out[u] = CrawlPriceResult(error="url_not_in_response")
        return out

    except httpx.TimeoutException:
        for u in urls:
            out[u] = CrawlPriceResult(error="timeout")
        return out
    except Exception as exc:
        for u in urls:
            out[u] = CrawlPriceResult(error=str(exc)[:200])
        return out


def _needs_retry(result: CrawlPriceResult) -> bool:
    return result.parsed is None


async def crawl_prices_async(urls: list[str]) -> dict[str, CrawlPriceResult]:
    unique = list(dict.fromkeys(u for u in urls if u and str(u).strip()))
    if not unique:
        return {}

    crawler_url = get_crawler_url()
    timeout = get_crawler_timeout()
    batch_size = get_crawler_batch_size()
    max_in_flight = get_crawler_max_in_flight()
    submit_interval = get_crawler_submit_interval()
    max_retries = get_crawler_max_retries()
    backoff = get_crawler_retry_backoff()

    results: dict[str, CrawlPriceResult] = {
        u: CrawlPriceResult(error="pending") for u in unique
    }
    pending = list(unique)
    sem = asyncio.Semaphore(max_in_flight)

    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries + 1):
            if not pending:
                break

            batches: list[list[str]] = []
            for i in range(0, len(pending), batch_size):
                batches.append(pending[i : i + batch_size])

            async def run_one_batch(batch: list[str]) -> dict[str, CrawlPriceResult]:
                async with sem:
                    return await _post_batch(client, crawler_url, batch, timeout)

            tasks: list[asyncio.Task[dict[str, CrawlPriceResult]]] = []
            for batch in batches:
                tasks.append(asyncio.create_task(run_one_batch(batch)))
                if submit_interval > 0:
                    await asyncio.sleep(submit_interval)

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for br in batch_results:
                if isinstance(br, Exception):
                    continue
                results.update(br)

            pending = [u for u in unique if _needs_retry(results[u])]
            if pending and attempt < max_retries:
                await asyncio.sleep(backoff * (2**attempt))

    return results


def crawl_prices(urls: list[str]) -> dict[str, CrawlPriceResult]:
    """Synchronous entry: crawl prices for a list of URLs."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(crawl_prices_async(urls))

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, crawl_prices_async(urls)).result()
