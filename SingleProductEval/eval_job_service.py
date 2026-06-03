"""
Backend-submitted report evaluation jobs: GT construction and metric computation.

searchTerm from backend is the user's full raw query (audit/callback only).
Metric ground truth is built exclusively from reportContent.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .eval_callback_client import build_callback_payload, notify_backend
from .metrics import compute_all_metrics

_PKG_DIR = Path(__file__).resolve().parent
BACKEND_JOBS_DIR = _PKG_DIR / "eval_logs" / "backend_jobs"


def _job_dir(run_id: str) -> Path:
    safe = re.sub(r"[^\w\-.]", "_", run_id)[:128]
    return BACKEND_JOBS_DIR / safe


def public_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in metrics.items() if not str(k).startswith("_")}


def _brand_from_report(report: dict[str, Any]) -> str:
    spu = report.get("spu_metadata") or {}
    for key in ("product_brand", "brand", "manufacturer"):
        val = spu.get(key)
        if val and str(val).strip():
            return str(val).strip()
    brand = report.get("brand")
    if brand and str(brand).strip():
        return str(brand).strip()
    return ""


def _model_from_report(report: dict[str, Any]) -> str:
    spu = report.get("spu_metadata") or {}
    val = spu.get("product_model")
    if val and str(val).strip():
        return str(val).strip()
    val = spu.get("product_name")
    if val and str(val).strip():
        return str(val).strip()
    name = report.get("name")
    if name and str(name).strip():
        return str(name).strip()
    return ""


def _product_name_from_report(report: dict[str, Any], model: str) -> str:
    spu = report.get("spu_metadata") or {}
    for key in ("product_name",):
        val = spu.get(key)
        if val and str(val).strip():
            return str(val).strip()
    name = report.get("name")
    if name and str(name).strip():
        return str(name).strip()
    return model


def _category_from_report(report: dict[str, Any]) -> str:
    spu = report.get("spu_metadata") or {}
    for key in ("product_category", "category"):
        val = spu.get(key)
        if val and str(val).strip():
            return str(val).strip().lower()
    sku = report.get("sku_discovery_data") or {}
    analysis = sku.get("product_analysis") or {}
    cat = analysis.get("category")
    if cat and str(cat).strip():
        return str(cat).strip().lower()
    return ""


def _expected_model_keywords_from_report(report: dict[str, Any], model: str) -> list[str]:
    keywords: list[str] = []
    if model:
        keywords.append(model)
    spu = report.get("spu_metadata") or {}
    product_name = str(spu.get("product_name") or report.get("name") or "").strip()
    if product_name and product_name not in keywords:
        if not model or model.lower() in product_name.lower():
            keywords.append(product_name)
    return keywords


def _spec_attributes_from_report(report: dict[str, Any]) -> dict[str, Any]:
    sel = report.get("defaultSelection")
    if isinstance(sel, dict) and sel:
        return dict(sel)
    return {}


def _collect_report_gt_warnings(
    report: dict[str, Any], model: str, category: str
) -> list[str]:
    warnings: list[str] = []
    if not report.get("spu_metadata"):
        warnings.append("report_missing_spu_metadata")
    if not model:
        warnings.append("report_missing_product_model")
    if not category:
        warnings.append("report_missing_category")
    return warnings


def build_gt_from_submit(
    search_term: str,
    report_content: dict[str, Any],
    run_id: str,
    report_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """
    Build GT for backend submit. search_term is stored for audit only; not used for metrics.
    """
    model_part = _model_from_report(report_content)
    category_slug = _category_from_report(report_content)
    brand = _brand_from_report(report_content)
    product_name = _product_name_from_report(report_content, model_part)
    warnings = _collect_report_gt_warnings(report_content, model_part, category_slug)

    gt: dict[str, Any] = {
        "id": run_id,
        "report_id": report_id,
        "search_term": (search_term or "").strip(),
        "user_model": model_part,
        "model": model_part,
        "category": category_slug,
        "brand": brand,
        "expected_model_keywords": _expected_model_keywords_from_report(
            report_content, model_part
        ),
        "spec_attributes": _spec_attributes_from_report(report_content),
        "brand_official_domains": [],
        "sku_discovery_data": {
            "product_analysis": {
                "category": category_slug,
                "model": model_part,
                "product_name": product_name,
                "brand": brand,
            },
        },
        "_report_first_gt": True,
    }
    if warnings:
        gt["_gt_warnings"] = warnings
    return gt, warnings


def persist_job_files(
    run_id: str,
    *,
    submit: dict[str, Any] | None = None,
    gt: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> Path:
    job_dir = _job_dir(run_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    if submit is not None:
        (job_dir / "submit.json").write_text(
            json.dumps(submit, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if gt is not None:
        (job_dir / "gt.json").write_text(
            json.dumps(gt, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if result is not None:
        (job_dir / "result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return job_dir


def load_job_result(run_id: str) -> dict[str, Any] | None:
    path = _job_dir(run_id) / "result.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_report_eval_job(
    *,
    run_id: str,
    report_id: str,
    search_term: str,
    report_content: dict[str, Any],
    enabled_metrics: list[str] | None,
) -> dict[str, Any]:
    """
    Synchronous job: build GT, compute metrics, persist, callback.
    """
    completed_at = datetime.now(timezone.utc).isoformat()
    gt, gt_warnings = build_gt_from_submit(
        search_term, report_content, run_id, report_id
    )

    submit_snapshot = {
        "reportId": report_id,
        "runId": run_id,
        "searchTerm": search_term,
    }
    persist_job_files(run_id, submit=submit_snapshot, gt=gt)

    status = "complete"
    error: str | None = None
    raw_metrics: dict[str, Any] = {}

    try:
        raw_metrics = compute_all_metrics(
            report_content, gt, enabled_metrics
        )
        if raw_metrics.get("_error"):
            status = "error"
            error = str(raw_metrics["_error"])
    except Exception as exc:
        status = "error"
        error = f"compute_all_metrics failed: {exc}"

    metrics_out = public_metrics(raw_metrics)
    success = status == "complete" and not error

    callback_payload = build_callback_payload(
        success=success,
        report_id=report_id,
        run_id=run_id,
        search_term=search_term,
        status=status,
        completed_at=completed_at,
        metrics=metrics_out,
        error=error,
    )
    callback_meta = notify_backend(callback_payload)

    result_doc: dict[str, Any] = {
        "runId": run_id,
        "reportId": report_id,
        "searchTerm": search_term,
        "status": status,
        "success": success,
        "completedAt": completed_at,
        "error": error,
        "gt_warnings": gt_warnings,
        "metrics": metrics_out,
        "raw_metrics": raw_metrics,
        "callback": callback_meta,
        "callback_payload": callback_payload,
    }
    if callback_meta.get("error") and not callback_meta.get("ok"):
        result_doc["_callback_error"] = callback_meta.get("error")

    persist_job_files(run_id, result=result_doc)
    return result_doc
