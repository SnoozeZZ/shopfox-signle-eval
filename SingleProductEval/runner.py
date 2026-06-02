"""
Eval runner: invokes the SingleProduct agent for each test case via the API,
polls for completion, and caches the final reports.

The runner calls the same /api/search endpoint the frontend uses, passing the
product model name as userPrompt and the pre-built skuDiscoveryData. No special
prompt template is needed — the agent treats it identically to a real search.

Supports two modes:
  1. Batch mode (run_all): CLI usage, returns results dict directly.
  2. Tracked mode (run_tracked): API usage, updates a shared progress dict
     in-place so the status endpoint can report live progress.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .config import (
    DEFAULT_API_BASE_URL,
    DEFAULT_CONCURRENCY,
    DEFAULT_POLL_INTERVAL_SEC,
    DEFAULT_TIMEOUT_SEC,
)

RESULTS_DIR = Path(__file__).parent / "results"
RUNS_DIR = RESULTS_DIR / "runs"
EVAL_REPORTS_DIR = Path(__file__).parent / "eval_reports"
EVAL_LOGS_DIR = Path(__file__).parent / "eval_logs"

LOGS_DIR = Path(__file__).parent.parent / "logs"

for _d in (RESULTS_DIR, RUNS_DIR, EVAL_REPORTS_DIR, EVAL_LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


async def _start_search(
    client: httpx.AsyncClient,
    base_url: str,
    test_case: dict,
) -> str:
    """POST /api/search with the product model and SKU data — same as frontend."""
    model = test_case["model"]
    specs = test_case.get("spec_attributes", {})
    if specs:
        spec_str = ", ".join(f"{v}" for v in specs.values())
        user_prompt = f"{model}, {spec_str}"
    else:
        user_prompt = model

    payload = {
        "userPrompt": user_prompt,
        "skuDiscoveryData": test_case["sku_discovery_data"],
    }
    resp = await client.post(f"{base_url}/api/search", json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Search start failed for {test_case['id']}: {data}")
    return data["searchId"]


async def _poll_until_complete(
    client: httpx.AsyncClient,
    base_url: str,
    search_id: str,
    test_id: str,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SEC,
) -> dict:
    """Poll /api/search/{id}/status until isComplete, ERROR, or timeout."""
    start = time.time()
    last_status = ""
    while time.time() - start < timeout_sec:
        resp = await client.get(
            f"{base_url}/api/search/{search_id}/status", timeout=30
        )
        resp.raise_for_status()
        status = resp.json()

        current = status.get("agentStatus", status.get("status", ""))
        if current != last_status:
            elapsed = time.time() - start
            print(f"  [{test_id}] {elapsed:6.1f}s  status={current}")
            last_status = current

        if status.get("isComplete"):
            return status
        if status.get("status") in ("ERROR", "CANCELLED"):
            return status

        await asyncio.sleep(poll_interval)

    raise TimeoutError(
        f"Search {search_id} for {test_id} did not complete within {timeout_sec}s"
    )


async def _fetch_report(
    client: httpx.AsyncClient, base_url: str, report_id: str
) -> dict:
    """GET /api/reports/{report_id}."""
    resp = await client.get(f"{base_url}/api/reports/{report_id}", timeout=30)
    resp.raise_for_status()
    return resp.json()


async def _run_single(
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
    base_url: str,
    test_case: dict,
    force: bool,
    on_complete: Callable | None = None,
) -> dict[str, Any]:
    """Run one test case end-to-end (with concurrency limit).

    Returns a dict with keys: report, search_id, report_id.
    """
    test_id = test_case["id"]
    report_path = RESULTS_DIR / f"{test_id}_report.json"

    if not force and report_path.exists():
        print(f"  [{test_id}] Using cached report: {report_path.name}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if on_complete:
            on_complete(test_id, "complete", report)
        return {"report": report, "search_id": None, "report_id": None}

    async with semaphore:
        print(f"  [{test_id}] Starting search...")
        if on_complete:
            on_complete(test_id, "running", None)
        try:
            search_id = await _start_search(client, base_url, test_case)
            print(f"  [{test_id}] searchId={search_id}")

            status = await _poll_until_complete(
                client, base_url, search_id, test_id
            )

            if status.get("status") in ("ERROR", "CANCELLED"):
                error_msg = status.get("error", "Unknown error")
                print(f"  [{test_id}] ERROR: {error_msg}")
                result = {"_eval_error": error_msg, "_test_id": test_id}
                if on_complete:
                    on_complete(test_id, "error", result)
                return {"report": result, "search_id": search_id, "report_id": None}

            report_id = status.get("reportId")
            if not report_id:
                print(f"  [{test_id}] ERROR: No reportId in status")
                result = {"_eval_error": "No reportId", "_test_id": test_id}
                if on_complete:
                    on_complete(test_id, "error", result)
                return {"report": result, "search_id": search_id, "report_id": None}

            print(f"  [{test_id}] Fetching report {report_id}...")
            report = await _fetch_report(client, base_url, report_id)

            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"  [{test_id}] Report saved to {report_path.name}")
            if on_complete:
                on_complete(test_id, "complete", report)
            return {"report": report, "search_id": search_id, "report_id": report_id}

        except Exception as exc:
            print(f"  [{test_id}] EXCEPTION: {exc}")
            result = {"_eval_error": str(exc), "_test_id": test_id}
            if on_complete:
                on_complete(test_id, "error", result)
            return {"report": result, "search_id": None, "report_id": None}


async def run_all(
    test_cases: list[dict],
    base_url: str = DEFAULT_API_BASE_URL,
    concurrency: int = DEFAULT_CONCURRENCY,
    force: bool = False,
) -> dict[str, Any]:
    """
    Run all test cases against the API and return {test_id: report_json}.
    Used by CLI (run_eval.py).
    """
    semaphore = asyncio.Semaphore(concurrency)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"  EVAL RUNNER — {len(test_cases)} products, concurrency={concurrency}")
    print(f"  API: {base_url}")
    print(f"  Force re-run: {force}")
    print(f"{'='*70}\n")

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{base_url}/health", timeout=5)
            resp.raise_for_status()
            print("  API health check: OK\n")
        except Exception as exc:
            print(f"  API health check FAILED: {exc}")
            print("  Make sure the API server is running.\n")
            return {}

        tasks = [
            _run_single(semaphore, client, base_url, tc, force)
            for tc in test_cases
        ]
        results = await asyncio.gather(*tasks)

    return {tc["id"]: r["report"] for tc, r in zip(test_cases, results)}


async def run_tracked(
    test_cases: list[dict],
    progress: dict,
    base_url: str = DEFAULT_API_BASE_URL,
    concurrency: int = DEFAULT_CONCURRENCY,
    force: bool = False,
) -> dict[str, Any]:
    """
    Run all test cases with live progress tracking.
    Used by the API background task. Mutates `progress` dict in-place so the
    status endpoint can read it at any time.

    Returns {test_id: {"report": ..., "search_id": ..., "report_id": ...}}.
    """
    semaphore = asyncio.Semaphore(concurrency)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def _on_complete(test_id: str, status: str, report: dict | None):
        progress["product_status"][test_id] = status
        if status == "running":
            if test_id not in progress["in_progress"]:
                progress["in_progress"].append(test_id)
        else:
            if test_id in progress["in_progress"]:
                progress["in_progress"].remove(test_id)
            if status == "complete":
                progress["completed"] += 1
            elif status == "error":
                progress["failed"] += 1

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{base_url}/health", timeout=5)
            resp.raise_for_status()
        except Exception as exc:
            progress["status"] = "error"
            progress["error"] = f"API health check failed: {exc}"
            return {}

        tasks = [
            _run_single(
                semaphore, client, base_url, tc, force, _on_complete,
            )
            for tc in test_cases
        ]
        results = await asyncio.gather(*tasks)

    return {tc["id"]: r for tc, r in zip(test_cases, results)}


def save_eval_artifacts(
    eval_run_id: str,
    results: dict[str, dict],
) -> None:
    """Copy reports and logs to eval_reports/ and eval_logs/ for an eval run."""
    run_reports_dir = EVAL_REPORTS_DIR / eval_run_id
    run_logs_dir = EVAL_LOGS_DIR / eval_run_id
    run_reports_dir.mkdir(parents=True, exist_ok=True)
    run_logs_dir.mkdir(parents=True, exist_ok=True)

    for test_id, result in results.items():
        report = result.get("report")
        search_id = result.get("search_id")

        if report and not report.get("_eval_error"):
            rpt_path = run_reports_dir / f"{test_id}.json"
            rpt_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        if search_id:
            log_src = LOGS_DIR / f"event_log_{search_id[:8]}.txt"
            if log_src.exists():
                log_dst = run_logs_dir / f"{test_id}.txt"
                log_dst.write_text(log_src.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                for candidate in LOGS_DIR.glob(f"event_log_{search_id[:8]}*"):
                    log_dst = run_logs_dir / f"{test_id}.txt"
                    log_dst.write_text(
                        candidate.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                    break


def load_cached_reports(test_cases: list[dict]) -> dict[str, Any]:
    """Load previously cached reports without running the agent."""
    reports = {}
    for tc in test_cases:
        test_id = tc["id"]
        report_path = RESULTS_DIR / f"{test_id}_report.json"
        if report_path.exists():
            reports[test_id] = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            print(f"  [{test_id}] No cached report found")
            reports[test_id] = {"_eval_error": "No cached report", "_test_id": test_id}
    return reports
