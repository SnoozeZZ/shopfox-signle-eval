"""Tests for external-callback payload transform (metric id as krId)."""

from __future__ import annotations

from SingleProductEval.eval_callback_transform import build_external_callback_payload


def test_metrics_use_metric_id():
    raw = {
        "spu_model_accuracy": 0.85,
        "kr4_1_top3_platform_coverage": 0.5,
        "top3_platform_coverage": 0.5,
    }
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="query",
        raw_metrics=raw,
        enabled_metrics=["spu_model_accuracy", "kr4_1_top3_platform_coverage", "top3_platform_coverage"],
    )
    kr_ids = {m["krId"] for m in payload["metrics"]}
    assert "spu_model_accuracy" in kr_ids
    assert "kr4_1_top3_platform_coverage" in kr_ids
    assert "top3_platform_coverage" not in kr_ids


def test_passed_when_value_not_null():
    raw = {"spu_model_accuracy": 0.85, "offer_link_accuracy": None}
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
        enabled_metrics=["spu_model_accuracy", "offer_link_accuracy"],
    )
    by_id = {m["krId"]: m for m in payload["metrics"]}
    assert by_id["spu_model_accuracy"]["passed"] is True
    assert by_id["spu_model_accuracy"]["value"] == "0.85"
    assert by_id["offer_link_accuracy"]["passed"] is False
    assert by_id["offer_link_accuracy"]["value"] == ""


def test_issues_from_kr3_9():
    raw = {
        "spu_model_accuracy": 0.5,
        "_kr3_9_issues": [
            {
                "retailer": "Amazon",
                "reason": "llm_rejected",
                "product_model": "X",
                "product_name": "Wrong product",
                "section": "priceComparison",
                "url": "https://example.com/p/1",
            }
        ],
    }
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
    )
    assert len(payload["issues"]) >= 1
    issue = payload["issues"][0]
    assert issue["attributionKr"] == "spu_model_accuracy"
    assert "Amazon" in issue["description"]
    assert issue["link"] == "https://example.com/p/1"
    assert issue["priority"] == "P1"


def test_kr3_1_string_issues():
    raw = {
        "key_info_valid": False,
        "_kr3_1_issues": ["priceComparison.offers[0] missing url"],
    }
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
    )
    assert any(
        i["attributionKr"] == "key_info_valid"
        and "missing url" in i["description"]
        for i in payload["issues"]
    )


def test_payload_top_level_keys():
    payload = build_external_callback_payload(
        run_id="run-abc",
        report_id="rpt-xyz",
        search_term="long query",
        raw_metrics={"report_success": "complete"},
        enabled_metrics=["report_success"],
    )
    assert payload["runId"] == "run-abc"
    assert payload["reportId"] == "rpt-xyz"
    assert payload["searchTerm"] == "long query"
    assert "metrics" in payload
    assert "issues" in payload
