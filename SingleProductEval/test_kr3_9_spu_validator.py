"""Unit tests for KR3-9 SPU model validator (non-semantic model + routing)."""

from __future__ import annotations

import json
from unittest.mock import patch

from SingleProductEval.kr3_9_spu_validator import (
    _is_invalid_model,
    _is_non_semantic_model,
    _llm_judge_batch,
    _route_offer,
    _semantic_product_model_for_llm,
)


def test_non_semantic_barcode_and_placeholders():
    assert _is_non_semantic_model("38100027764")
    assert _is_non_semantic_model("00038100168610")
    assert _is_non_semantic_model("Item model number : 00038100168610")
    assert _is_non_semantic_model("model number: 12345")
    assert _is_non_semantic_model("B0DP3GQ4QY")
    assert _is_non_semantic_model("")
    assert _is_non_semantic_model("n/a")
    assert _is_non_semantic_model("unknown")
    assert _is_invalid_model("38100027764")


def test_semantic_model_names_remain_valid():
    assert not _is_non_semantic_model("Galaxy S25 Ultra")
    assert not _is_non_semantic_model("Pro Plan Small Breed Dog Food Chicken and Rice Formula")
    assert not _is_non_semantic_model("Leica Q3")
    assert not _is_non_semantic_model("Q3")  # short alphanumeric, not digit SKU
    assert _semantic_product_model_for_llm("Galaxy S25 Ultra") == "Galaxy S25 Ultra"
    assert _semantic_product_model_for_llm("38100027764") == ""
    assert _semantic_product_model_for_llm("Item model number : 00038100168610") == ""


def test_route_barcode_with_title_needs_llm():
    offer = {
        "product_model": "38100027764",
        "product_name": "Purina Pro Plan Classic Pate Dog Food",
    }
    assert _route_offer(offer, "pro plan chicken & rice") == "needs_llm"


def test_route_barcode_without_title_empty_mismatch():
    offer = {"product_model": "38100027764", "product_name": ""}
    assert _route_offer(offer, "pro plan chicken & rice") == "empty_mismatch"


def test_route_exact_match_semantic_only():
    offer = {
        "product_model": "Galaxy S25 Ultra",
        "product_name": "Samsung phone",
    }
    assert _route_offer(offer, "Galaxy S25 Ultra") == "exact_match"
    # Barcode equal to a numeric user_model must NOT exact-match
    assert (
        _route_offer(
            {"product_model": "12345", "product_name": "x"},
            "12345",
        )
        == "needs_llm"
    )


def test_llm_payload_strips_non_semantic_model():
    captured: dict = {}

    def fake_chat_json(system, user, model=None, enable_thinking=False):
        captured["payload"] = json.loads(user)
        return [
            {"index": 0, "match": True, "reason": "ok"},
            {"index": 1, "match": True, "reason": "ok"},
        ]

    batch = [
        (
            0,
            {
                "retailer": "Amazon",
                "product_model": "38100027764",
                "product_name": "Purina Pro Plan Chicken & Rice",
            },
        ),
        (
            1,
            {
                "retailer": "Walmart",
                "product_model": "Pro Plan Chicken & Rice",
                "product_name": "Purina Pro Plan Dry Dog Food",
            },
        ),
    ]

    with patch(
        "SingleProductEval.kr3_9_spu_validator.chat_json",
        side_effect=fake_chat_json,
    ):
        results = _llm_judge_batch("pro plan chicken & rice", batch)

    assert results[0][0] is True
    assert results[1][0] is True
    offers = captured["payload"]["offers"]
    assert offers[0]["product_model"] == ""
    assert offers[0]["product_name"] == "Purina Pro Plan Chicken & Rice"
    assert offers[1]["product_model"] == "Pro Plan Chicken & Rice"
