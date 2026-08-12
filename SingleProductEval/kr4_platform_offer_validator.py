"""
KR4 validators: 5 platforms and 20 offers threshold on all offers.
"""

from __future__ import annotations

from typing import Any

from .config import KR4_MIN_OFFERS, KR4_MIN_PLATFORMS


def evaluate_kr4_platform_offer_threshold(
    platform_count: int,
    offer_count: int,
    min_platforms: int | None = None,
    min_offers: int | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Returns (passed, stats).
    Zero offers always fails.
    """
    min_p = KR4_MIN_PLATFORMS if min_platforms is None else min_platforms
    min_o = KR4_MIN_OFFERS if min_offers is None else min_offers

    platforms_ok = platform_count >= min_p
    offers_ok = offer_count >= min_o

    if offer_count == 0:
        passed = False
    else:
        passed = platforms_ok and offers_ok

    stats: dict[str, Any] = {
        "offer_count": offer_count,
        "platform_count": platform_count,
        "min_platforms": min_p,
        "min_offers": min_o,
        "platforms_ok": platforms_ok,
        "offers_ok": offers_ok,
        "passed": passed,
    }
    return passed, stats
