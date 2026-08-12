"""Tests for KR4 5-platform / 20-offer threshold."""

from __future__ import annotations

from SingleProductEval.kr4_platform_offer_validator import (
    evaluate_kr4_platform_offer_threshold,
)


def test_five_platforms_twenty_offers_passes():
    passed, stats = evaluate_kr4_platform_offer_threshold(5, 20)
    assert passed is True
    assert stats["platforms_ok"] is True
    assert stats["offers_ok"] is True


def test_nineteen_offers_fails():
    passed, stats = evaluate_kr4_platform_offer_threshold(5, 19)
    assert passed is False
    assert stats["platforms_ok"] is True
    assert stats["offers_ok"] is False


def test_four_platforms_fails():
    passed, stats = evaluate_kr4_platform_offer_threshold(4, 20)
    assert passed is False
    assert stats["platforms_ok"] is False
    assert stats["offers_ok"] is True


def test_zero_offers_fails():
    passed, stats = evaluate_kr4_platform_offer_threshold(5, 0)
    assert passed is False
