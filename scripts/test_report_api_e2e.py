#!/usr/bin/env python3
"""
E2E smoke test for POST /api/eval/report/submit and job status/result endpoints.

Usage (server must be running):
    .venv/bin/uvicorn api_server:app --host 127.0.0.1 --port 8765
    .venv/bin/python scripts/test_report_api_e2e.py --base-url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
GALAXY_REPORT = ROOT / "SingleProductEval" / "results" / "galaxy_s25_ultra_report.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--poll-sec", type=int, default=120, help="Max wait for job complete")
    parser.add_argument("--use-galaxy", action="store_true", help="Use full galaxy report (slow)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    client = httpx.Client(timeout=60.0)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = ""):
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{name}: {detail}")

    # 1. Health
    try:
        r = client.get(f"{base}/health")
        check("GET /health", r.status_code == 200 and r.json().get("status") == "ok", str(r.status_code))
    except Exception as exc:
        check("GET /health", False, str(exc))
        print("\n请先启动服务: .venv/bin/uvicorn api_server:app --host 127.0.0.1 --port 8765")
        return 1

    # 2. Invalid submit
    r = client.post(
        f"{base}/api/eval/report/submit",
        json={
            "reportId": "r1",
            "runId": "run-invalid",
            "searchTerm": "smartphones Galaxy S25 Ultra",
            "reportContent": {},
        },
    )
    check("POST submit empty reportContent -> 422", r.status_code == 422, r.text[:200])

    # 3. Valid submit (minimal report for speed unless --use-galaxy)
    run_id = f"test-{uuid.uuid4().hex[:12]}"
    if args.use_galaxy and GALAXY_REPORT.exists():
        report_content = json.loads(GALAXY_REPORT.read_text(encoding="utf-8"))
        label = "galaxy full report"
    else:
        report_content = {
            "name": "Samsung Galaxy S25 Ultra",
            "brand": "Samsung",
            "spu_metadata": {
                "product_model": "Galaxy S25 Ultra",
                "product_brand": "Samsung",
                "product_category": "smartphones",
                "original_query": "Galaxy S25 Ultra",
            },
            "priceComparison": {"offers": [], "rebatesAndCoupons": []},
            "finalRecommendation": None,
        }
        label = "minimal report"

    r = client.post(
        f"{base}/api/eval/report/submit",
        json={
            "reportId": "test-report-id-001",
            "runId": run_id,
            "searchTerm": "smartphones Galaxy S25 Ultra",
            "reportContent": report_content,
        },
        timeout=120.0,
    )
    check(
        "POST /api/eval/report/submit",
        r.status_code == 200 and r.json().get("success") is True,
        f"{r.status_code} {r.text[:300]}",
    )
    if r.status_code != 200:
        return 1

    body = r.json()
    check("submit returns runId", body.get("runId") == run_id, json.dumps(body))

    # 4. Status poll
    deadline = time.time() + args.poll_sec
    last_status = None
    while time.time() < deadline:
        sr = client.get(f"{base}/api/eval/report/jobs/{run_id}/status")
        if sr.status_code != 200:
            check("GET job status", False, f"{sr.status_code} {sr.text[:200]}")
            break
        last_status = sr.json().get("status")
        print(f"  ... status={last_status}")
        if last_status in ("complete", "error"):
            break
        time.sleep(3)

    check(
        "job reached terminal state",
        last_status in ("complete", "error"),
        f"last={last_status} (waited {args.poll_sec}s, payload={label})",
    )

    if last_status == "complete":
        rr = client.get(f"{base}/api/eval/report/jobs/{run_id}/result")
        check("GET job result", rr.status_code == 200, str(rr.status_code))
        if rr.status_code == 200:
            res = rr.json()
            metrics = res.get("metrics") or {}
            n = len(metrics)
            check("result has metrics", n > 0, f"{n} metric keys")
            print(f"  sample metrics: {list(metrics.keys())[:8]}...")
    elif last_status == "error":
        sr = client.get(f"{base}/api/eval/report/jobs/{run_id}/status")
        print(f"  error: {sr.json().get('error')}")

    # 5. Unknown job
    r404 = client.get(f"{base}/api/eval/report/jobs/nonexistent-run-id/status")
    check("GET unknown job -> 404", r404.status_code == 404, str(r404.status_code))

    print()
    if failures:
        print("失败项:", *failures, sep="\n  ")
        return 1
    print("全部检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
