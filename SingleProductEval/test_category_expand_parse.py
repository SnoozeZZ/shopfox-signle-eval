"""Tests for category/expand response parsing (KR4-5)."""

from __future__ import annotations

import json
from pathlib import Path

from SingleProductEval.category_expand_client import parse_expand_response
from SingleProductEval.url_normalize import normalize_url

_FIXTURE = Path(__file__).parent / "fixtures" / "category_expand_sample.json"


def test_parse_fixture_has_items():
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    items = parse_expand_response(payload)
    assert len(items) >= 2
    urls = [i["url"] for i in items]
    assert any("amazon.com/dp/" in u for u in urls)


def test_normalize_crawler_fields():
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    items = parse_expand_response(payload)
    samsung = next(i for i in items if "B0DP3GQ4QY" in i["url"])
    assert "Galaxy S25 Ultra" in samsung["product_name"]
    assert "Samsung" in samsung["product_model"]
    assert samsung["platform"] == "amazon"


def test_normalize_url_strips_tracking():
    u1 = normalize_url("https://www.amazon.com/dp/B0DP3GQ4QY?tag=track123")
    u2 = normalize_url("https://amazon.com/dp/B0DP3GQ4QY")
    assert u1 == u2
