"""Tests for external-callback payload transform (metric id as krId)."""

from __future__ import annotations

from SingleProductEval.config import CALLBACK_METRIC_IDS
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
    assert "top3_platform_coverage" in kr_ids
    assert "kr4_1_top3_platform_coverage" not in kr_ids


def test_callback_fixed_22_metrics():
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics={},
    )
    assert len(payload["metrics"]) == 22
    assert [m["krId"] for m in payload["metrics"]] == list(CALLBACK_METRIC_IDS)
    assert all(m["passed"] is False for m in payload["metrics"])
    assert all(m["value"] == "" for m in payload["metrics"])


def test_canonical_fallback_value():
    raw = {"kr4_1_top3_platform_coverage": 0.67}
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
    )
    by_id = {m["krId"]: m for m in payload["metrics"]}
    assert by_id["top3_platform_coverage"]["value"] == "0.67"
    assert by_id["top3_platform_coverage"]["passed"] is True
    assert "kr4_1_top3_platform_coverage" not in by_id


def test_no_extra_metrics_in_callback():
    raw = {
        "spec_id_completeness": 1.0,
        "total_platform_count": 5,
        "kr4_1_top3_platform_coverage": 0.5,
        "report_success": "complete",
    }
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
    )
    kr_ids = {m["krId"] for m in payload["metrics"]}
    assert kr_ids == set(CALLBACK_METRIC_IDS)
    assert "spec_id_completeness" not in kr_ids
    assert "total_platform_count" not in kr_ids
    assert "kr4_1_top3_platform_coverage" not in kr_ids


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
                "user_model": "Galaxy S25 Ultra",
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
    assert "Search" in issue["description"]
    assert "shows" in issue["description"]
    assert "Amazon" in issue["description"]
    assert issue["link"] == "https://example.com/p/1"
    assert issue["priority"] == "P1"


def test_kr3_11_price_description():
    raw = {
        "offer_price_accuracy": 0.5,
        "_kr3_11_issues": [
            {
                "retailer": "Amazon",
                "recorded_price": 499,
                "crawled_price": "$549",
                "product_name": "Galaxy S25 Ultra",
                "reason": "price_mismatch",
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
    assert len(payload["issues"]) == 1
    issue = payload["issues"][0]
    assert issue["attributionKr"] == "offer_price_accuracy"
    assert "$499" in issue["description"]
    assert "$549" in issue["description"]
    assert "Amazon" in issue["description"]
    assert issue["priority"] == "P0"


def test_exclude_http_inconclusive():
    raw = {
        "_kr3_8_issues": [
            {
                "retailer": "Walmart",
                "url": "https://example.com/p/1",
                "reason": "http_inconclusive",
                "detail": "HTTP 403",
                "section": "priceComparison",
            }
        ],
    }
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
    )
    assert payload["issues"] == []


def test_no_eval_warnings_in_issues():
    raw = {
        "_error": "crawler down",
        "_warnings": ["kr3_11: crawler unavailable"],
        "report_success": "fail",
        "_kr3_9_issues": [],
    }
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
    )
    assert payload["issues"] == []


def test_exclude_kr3_13_unverifiable():
    raw = {
        "_kr3_13_issues": [
            {
                "retailer": "Amazon",
                "source": "rakuten",
                "url": "https://example.com/rebate",
                "reason": "no_page_text",
                "section": "priceComparison.rebatesAndCoupons",
            }
        ],
    }
    payload = build_external_callback_payload(
        run_id="run-1",
        report_id="rpt-1",
        search_term="q",
        raw_metrics=raw,
    )
    assert payload["issues"] == []


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
        and i["priority"] == "P0"
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
