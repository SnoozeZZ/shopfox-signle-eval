"""Tests for backend job GT construction (report-first, searchTerm audit-only)."""

from __future__ import annotations

from SingleProductEval.eval_job_service import build_gt_from_submit

GALAXY_LONG_QUERY = (
    "I need to purchase Galaxy S25 Ultra, i need you to search all the major "
    "websites to compare the prices for me covering at least 5 major e-commerce "
    "websites, and search for at least 20 product links and consolidate the result"
)

GALAXY_LIKE_REPORT = {
    "name": "Samsung Galaxy S25 Ultra",
    "brand": "Samsung",
    "spu_metadata": {
        "original_query": GALAXY_LONG_QUERY,
        "product_name": "Samsung Galaxy S25 Ultra",
        "product_model": "Galaxy S25 Ultra",
        "product_brand": "Samsung",
        "product_category": "smartphones",
    },
    "defaultSelection": {"condition": "New"},
    "priceComparison": {"offers": []},
}


def test_build_gt_from_galaxy_like_report():
    gt, warnings = build_gt_from_submit(
        GALAXY_LONG_QUERY,
        GALAXY_LIKE_REPORT,
        "run-test-001",
        "report-uuid-001",
    )
    assert gt["_report_first_gt"] is True
    assert gt["search_term"] == GALAXY_LONG_QUERY
    assert gt["user_model"] == "Galaxy S25 Ultra"
    assert gt["model"] == "Galaxy S25 Ultra"
    assert gt["category"] == "smartphones"
    assert gt["brand"] == "Samsung"
    assert "Galaxy S25 Ultra" in gt["expected_model_keywords"]
    assert gt["spec_attributes"] == {"condition": "New"}
    analysis = gt["sku_discovery_data"]["product_analysis"]
    assert analysis["category"] == "smartphones"
    assert analysis["model"] == "Galaxy S25 Ultra"
    assert warnings == []


def test_build_gt_ignores_search_term_for_model():
    report = {
        "name": "Samsung Galaxy S25 Ultra",
        "spu_metadata": {
            "product_model": "Galaxy S25 Ultra",
            "product_brand": "Samsung",
            "product_category": "smartphones",
        },
    }
    wrong_query = "I want to buy a completely different product XYZ-999"
    gt, _ = build_gt_from_submit(
        wrong_query,
        report,
        "run-test-002",
        "report-uuid-002",
    )
    assert gt["user_model"] == "Galaxy S25 Ultra"
    assert gt["search_term"] == wrong_query


def test_build_gt_warnings_when_report_thin():
    gt, warnings = build_gt_from_submit(
        GALAXY_LONG_QUERY,
        {"priceComparison": {"offers": []}},
        "run-test-003",
        "report-uuid-003",
    )
    assert "report_missing_spu_metadata" in warnings
    assert "report_missing_product_model" in warnings
    assert "report_missing_category" in warnings
    assert gt["user_model"] == ""
    assert gt["search_term"] == GALAXY_LONG_QUERY


def test_derive_user_model_skips_search_term_for_report_first_gt():
    from SingleProductEval.kr3_9_spu_validator import derive_user_model

    report = GALAXY_LIKE_REPORT
    gt = {
        "user_model": "Galaxy S25 Ultra",
        "search_term": GALAXY_LONG_QUERY,
        "_report_first_gt": True,
    }
    assert derive_user_model(report, gt) == "Galaxy S25 Ultra"

    gt_empty_model = {
        "user_model": "",
        "search_term": GALAXY_LONG_QUERY,
        "_report_first_gt": True,
    }
    assert derive_user_model(report, gt_empty_model) == "Galaxy S25 Ultra"
