"""
FastAPI router for the SingleProduct eval pipeline.

Mount in api_server.py:
    from SingleProductEval.api_routes import eval_router
    app.include_router(eval_router, prefix="/api/eval", tags=["eval"])
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .config import (
    DEFAULT_API_BASE_URL,
    DEFAULT_CONCURRENCY,
    DEFAULT_RUBRIC,
    METRICS_REGISTRY,
)
from .metrics import compute_all_metrics
from .report_generator import _compute_summary_row, generate_csv
from .runner import (
    EVAL_LOGS_DIR,
    EVAL_REPORTS_DIR,
    RESULTS_DIR,
    RUNS_DIR,
    load_cached_reports,
    run_tracked,
    save_eval_artifacts,
)

eval_router = APIRouter()

GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"
RUBRIC_CONFIG_PATH = Path(__file__).parent / "rubric_config.json"

_active_runs: dict[str, dict] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

class EvalProductRequest(BaseModel):
    id: str
    model: str
    category: str
    brand: str
    expected_model_keywords: list[str] = []
    spec_attributes: dict = {}
    brand_official_domains: list[str] = []
    sku_discovery_data: dict = {}


class EvalRunRequest(BaseModel):
    product_ids: Optional[list[str]] = None
    force: bool = False
    concurrency: int = DEFAULT_CONCURRENCY


class EvalRubricUpdate(BaseModel):
    enabled_metrics: Optional[list[str]] = None
    min_platforms: Optional[int] = None
    min_product_links: Optional[int] = None
    top3_slots: Optional[list[dict]] = None
    top5_extra_slots: Optional[list[dict]] = None
    retailer_aliases: Optional[dict[str, str]] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Ground Truth I/O
# ═══════════════════════════════════════════════════════════════════════════════

def _load_ground_truth() -> dict:
    if GROUND_TRUTH_PATH.exists():
        return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    return {"test_cases": []}


def _save_ground_truth(data: dict):
    GROUND_TRUTH_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _load_rubric() -> dict:
    defaults = dict(DEFAULT_RUBRIC)
    if RUBRIC_CONFIG_PATH.exists():
        try:
            overrides = json.loads(RUBRIC_CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update({k: v for k, v in overrides.items() if v is not None})
        except Exception:
            pass
    return defaults


def _save_rubric(data: dict):
    RUBRIC_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Products CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@eval_router.get("/products")
async def list_products():
    gt = _load_ground_truth()
    return {"products": gt.get("test_cases", []), "count": len(gt.get("test_cases", []))}


@eval_router.get("/products/{product_id}")
async def get_product(product_id: str):
    gt = _load_ground_truth()
    for tc in gt.get("test_cases", []):
        if tc["id"] == product_id:
            return tc
    raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")


@eval_router.post("/products")
async def add_product(product: EvalProductRequest):
    gt = _load_ground_truth()
    cases = gt.get("test_cases", [])
    if any(tc["id"] == product.id for tc in cases):
        raise HTTPException(status_code=409, detail=f"Product '{product.id}' already exists")
    cases.append(product.model_dump())
    gt["test_cases"] = cases
    _save_ground_truth(gt)
    return {"success": True, "id": product.id, "count": len(cases)}


@eval_router.put("/products/{product_id}")
async def update_product(product_id: str, product: EvalProductRequest):
    gt = _load_ground_truth()
    cases = gt.get("test_cases", [])
    for i, tc in enumerate(cases):
        if tc["id"] == product_id:
            updated = product.model_dump()
            updated["id"] = product_id
            cases[i] = updated
            gt["test_cases"] = cases
            _save_ground_truth(gt)
            return {"success": True, "id": product_id}
    raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")


@eval_router.delete("/products/{product_id}")
async def delete_product(product_id: str):
    gt = _load_ground_truth()
    cases = gt.get("test_cases", [])
    new_cases = [tc for tc in cases if tc["id"] != product_id]
    if len(new_cases) == len(cases):
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    gt["test_cases"] = new_cases
    _save_ground_truth(gt)
    return {"success": True, "id": product_id, "count": len(new_cases)}


# ═══════════════════════════════════════════════════════════════════════════════
# Rubric Config (= Metrics Configuration)
# ═══════════════════════════════════════════════════════════════════════════════

@eval_router.get("/rubric")
async def get_rubric():
    rubric = _load_rubric()
    rubric["metrics_registry"] = METRICS_REGISTRY
    return rubric


@eval_router.put("/rubric")
async def update_rubric(rubric: EvalRubricUpdate):
    current = _load_rubric()
    updates = rubric.model_dump(exclude_none=True)
    current.update(updates)
    _save_rubric(current)
    return {"success": True, "rubric": current}


@eval_router.post("/rubric/reset")
async def reset_rubric():
    if RUBRIC_CONFIG_PATH.exists():
        RUBRIC_CONFIG_PATH.unlink()
    return {"success": True, "rubric": _load_rubric()}


# ═══════════════════════════════════════════════════════════════════════════════
# Eval Run — Start & Status
# ═══════════════════════════════════════════════════════════════════════════════

@eval_router.post("/run")
async def start_eval_run(request: EvalRunRequest):
    gt = _load_ground_truth()
    all_cases = gt.get("test_cases", [])

    if request.product_ids:
        cases = [tc for tc in all_cases if tc["id"] in request.product_ids]
        missing = set(request.product_ids) - {tc["id"] for tc in cases}
        if missing:
            raise HTTPException(status_code=404, detail=f"Products not found: {', '.join(missing)}")
    else:
        cases = all_cases

    if not cases:
        raise HTTPException(status_code=400, detail="No products to evaluate")

    eval_run_id = str(uuid.uuid4())
    rubric = _load_rubric()

    progress = {
        "eval_run_id": eval_run_id,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "total": len(cases),
        "completed": 0,
        "failed": 0,
        "in_progress": [],
        "product_status": {tc["id"]: "pending" for tc in cases},
        "product_ids": [tc["id"] for tc in cases],
        "rubric_snapshot": rubric,
        "force": request.force,
        "concurrency": request.concurrency,
        "results": None,
        "error": None,
    }
    _active_runs[eval_run_id] = progress

    asyncio.create_task(
        _background_eval_run(eval_run_id, cases, rubric, request.force, request.concurrency)
    )

    return {"success": True, "eval_run_id": eval_run_id, "product_count": len(cases)}


async def _background_eval_run(
    eval_run_id: str,
    cases: list[dict],
    rubric: dict,
    force: bool,
    concurrency: int,
):
    progress = _active_runs[eval_run_id]
    enabled_metrics = rubric.get("enabled_metrics")

    try:
        raw_results = await run_tracked(
            test_cases=cases,
            progress=progress,
            base_url=DEFAULT_API_BASE_URL,
            concurrency=concurrency,
            force=force,
        )

        save_eval_artifacts(eval_run_id, raw_results)

        all_metrics: list[dict] = []
        product_results: list[dict] = []
        for tc in cases:
            test_id = tc["id"]
            result_entry = raw_results.get(test_id, {})
            report = result_entry.get("report", {"_eval_error": "Missing report"}) if isinstance(result_entry, dict) else result_entry
            m = compute_all_metrics(report, tc, enabled_metrics)
            all_metrics.append(m)
            search_id = result_entry.get("search_id") if isinstance(result_entry, dict) else None
            report_id = result_entry.get("report_id") if isinstance(result_entry, dict) else None
            product_results.append({
                "product_id": test_id,
                "model": tc["model"],
                "category": tc["category"],
                "status": "error" if m.get("_error") else "complete",
                "error": m.get("_error"),
                "metrics": {k: v for k, v in m.items() if not k.startswith("_")},
                "report_file": f"{test_id}_report.json",
                "search_id": search_id,
                "report_id": report_id,
            })

        summary = _compute_summary_row(all_metrics, cases)

        run_data = {
            "eval_run_id": eval_run_id,
            "started_at": progress["started_at"],
            "completed_at": datetime.now().isoformat(),
            "status": "complete",
            "rubric_snapshot": rubric,
            "product_count": len(cases),
            "completed_count": progress["completed"],
            "failed_count": progress["failed"],
            "results": product_results,
            "summary": summary,
        }

        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_path = RUNS_DIR / f"run_{ts}_{eval_run_id[:8]}.json"
        run_path.write_text(
            json.dumps(run_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        progress["status"] = "complete"
        progress["completed_at"] = run_data["completed_at"]
        progress["results"] = run_data
        progress["run_file"] = run_path.name

    except Exception as exc:
        progress["status"] = "error"
        progress["error"] = str(exc)
        progress["completed_at"] = datetime.now().isoformat()


@eval_router.get("/run/{eval_run_id}/status")
async def get_eval_run_status(eval_run_id: str):
    progress = _active_runs.get(eval_run_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"Eval run '{eval_run_id}' not found")

    resp: dict[str, Any] = {
        "eval_run_id": eval_run_id,
        "status": progress["status"],
        "started_at": progress["started_at"],
        "completed_at": progress.get("completed_at"),
        "total": progress["total"],
        "completed": progress["completed"],
        "failed": progress["failed"],
        "in_progress": progress["in_progress"],
        "product_status": progress["product_status"],
        "error": progress.get("error"),
    }

    if progress["status"] == "complete" and progress.get("results"):
        resp["results"] = progress["results"]

    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# History — List & Retrieve Past Runs
# ═══════════════════════════════════════════════════════════════════════════════

@eval_router.get("/runs")
async def list_runs():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_files = sorted(RUNS_DIR.glob("run_*.json"), reverse=True)

    runs: list[dict] = []
    for path in run_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            runs.append({
                "eval_run_id": data.get("eval_run_id", ""),
                "file": path.name,
                "started_at": data.get("started_at", ""),
                "completed_at": data.get("completed_at", ""),
                "status": data.get("status", ""),
                "product_count": data.get("product_count", 0),
                "completed_count": data.get("completed_count", 0),
                "failed_count": data.get("failed_count", 0),
                "summary": data.get("summary"),
            })
        except Exception:
            continue

    return {"runs": runs, "count": len(runs)}


@eval_router.get("/runs/{eval_run_id}")
async def get_run(eval_run_id: str):
    run_data = _find_run(eval_run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{eval_run_id}' not found")
    return run_data


@eval_router.get("/runs/{eval_run_id}/csv")
async def get_run_csv(eval_run_id: str):
    run_data = _find_run(eval_run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{eval_run_id}' not found")

    product_results = run_data.get("results", [])
    test_cases = [
        {"model": r["model"], "category": r["category"], "id": r["product_id"]}
        for r in product_results
    ]
    all_metrics = [r.get("metrics", {}) for r in product_results]
    csv_content = generate_csv(all_metrics, test_cases)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="eval_{eval_run_id[:8]}.csv"'},
    )


@eval_router.get("/runs/{eval_run_id}/products/{product_id}")
async def get_run_product_detail(eval_run_id: str, product_id: str):
    run_data = _find_run(eval_run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{eval_run_id}' not found")

    for r in run_data.get("results", []):
        if r["product_id"] == product_id:
            result: dict[str, Any] = dict(r)
            report_path = RESULTS_DIR / r.get("report_file", "")
            if report_path.exists():
                result["raw_report"] = json.loads(report_path.read_text(encoding="utf-8"))
            return result

    raise HTTPException(
        status_code=404,
        detail=f"Product '{product_id}' not found in run '{eval_run_id}'",
    )


@eval_router.post("/runs/{eval_run_id}/reevaluate")
async def reevaluate_run(eval_run_id: str):
    run_data = _find_run(eval_run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{eval_run_id}' not found")

    gt = _load_ground_truth()
    gt_map = {tc["id"]: tc for tc in gt.get("test_cases", [])}
    rubric = _load_rubric()
    enabled_metrics = rubric.get("enabled_metrics")

    product_results = run_data.get("results", [])
    new_results: list[dict] = []
    all_metrics: list[dict] = []
    cases_for_summary: list[dict] = []

    for r in product_results:
        pid = r["product_id"]
        tc = gt_map.get(pid)
        if not tc:
            new_results.append(r)
            continue

        report_path = RESULTS_DIR / r.get("report_file", "")
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            report = {"_eval_error": "No cached report"}

        m = compute_all_metrics(report, tc, enabled_metrics)
        all_metrics.append(m)
        cases_for_summary.append(tc)

        new_results.append({
            "product_id": pid,
            "model": tc["model"],
            "category": tc["category"],
            "status": "error" if m.get("_error") else "complete",
            "error": m.get("_error"),
            "metrics": {k: v for k, v in m.items() if not k.startswith("_")},
            "report_file": r.get("report_file", ""),
            "search_id": r.get("search_id"),
            "report_id": r.get("report_id"),
        })

    summary = _compute_summary_row(all_metrics, cases_for_summary) if all_metrics else {}

    new_run_id = str(uuid.uuid4())
    new_run = {
        "eval_run_id": new_run_id,
        "started_at": datetime.now().isoformat(),
        "completed_at": datetime.now().isoformat(),
        "status": "complete",
        "rubric_snapshot": rubric,
        "product_count": len(new_results),
        "completed_count": sum(1 for r in new_results if r.get("status") == "complete"),
        "failed_count": sum(1 for r in new_results if r.get("status") == "error"),
        "results": new_results,
        "summary": summary,
        "reevaluated_from": eval_run_id,
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_path = RUNS_DIR / f"run_{ts}_{new_run_id[:8]}.json"
    run_path.write_text(
        json.dumps(new_run, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {"success": True, "eval_run_id": new_run_id, "file": run_path.name}


# ═══════════════════════════════════════════════════════════════════════════════
# Eval Reports & Logs
# ═══════════════════════════════════════════════════════════════════════════════

@eval_router.get("/runs/{eval_run_id}/logs/{product_id}")
async def get_eval_log(eval_run_id: str, product_id: str):
    log_path = EVAL_LOGS_DIR / eval_run_id / f"{product_id}.txt"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log not found")
    return PlainTextResponse(log_path.read_text(encoding="utf-8"))


@eval_router.get("/runs/{eval_run_id}/reports/{product_id}")
async def get_eval_report(eval_run_id: str, product_id: str):
    rpt_path = EVAL_REPORTS_DIR / eval_run_id / f"{product_id}.json"
    if not rpt_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return json.loads(rpt_path.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _find_run(eval_run_id: str) -> dict | None:
    if eval_run_id in _active_runs:
        result = _active_runs[eval_run_id].get("results")
        if result:
            return result

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    for path in RUNS_DIR.glob("run_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("eval_run_id") == eval_run_id:
                return data
        except Exception:
            continue

    for path in RUNS_DIR.glob(f"run_*_{eval_run_id[:8]}*.json"):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

    return None
