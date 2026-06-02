"""
CLI entry point for the SingleProduct evaluation pipeline.

Usage:
    # Full eval (all 20 products) — requires API server running
    python -m SingleProductEval.run_eval

    # Single product by name substring
    python -m SingleProductEval.run_eval --product "Galaxy S25"

    # Evaluate cached reports only (no agent execution)
    python -m SingleProductEval.run_eval --eval-only

    # Force re-run (ignore cache)
    python -m SingleProductEval.run_eval --force

    # Custom concurrency & output
    python -m SingleProductEval.run_eval --concurrency 5 --output csv --output-path results/eval.csv

    # Custom API server URL
    python -m SingleProductEval.run_eval --api-url http://localhost:8001
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure parent is importable when running as a module
_pkg_dir = str(Path(__file__).resolve().parent.parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from SingleProductEval.config import DEFAULT_API_BASE_URL, DEFAULT_CONCURRENCY
from SingleProductEval.metrics import compute_all_metrics
from SingleProductEval.report_generator import (
    generate_console_table,
    generate_csv,
    generate_json_report,
)
from SingleProductEval.runner import load_cached_reports, run_all

GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"
RESULTS_DIR = Path(__file__).parent / "results"


def _load_ground_truth() -> list[dict]:
    data = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    return data["test_cases"]


def _filter_cases(cases: list[dict], product_filter: str | None) -> list[dict]:
    if not product_filter:
        return cases
    needle = product_filter.lower()
    matched = [tc for tc in cases if needle in tc["model"].lower() or needle in tc["id"]]
    if not matched:
        print(f"No test case matching '{product_filter}'. Available:")
        for tc in cases:
            print(f"  - {tc['id']}: {tc['model']}")
        sys.exit(1)
    return matched


def main():
    parser = argparse.ArgumentParser(
        description="SingleProduct Eval Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--product", "-p",
        help="Filter to a single product (name substring or test_id)",
    )
    parser.add_argument(
        "--eval-only",
        action="store_true",
        help="Skip agent execution, evaluate cached reports only",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force re-run all products (ignore cached reports)",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max parallel agent runs (default: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_BASE_URL,
        help=f"API server URL (default: {DEFAULT_API_BASE_URL})",
    )
    parser.add_argument(
        "--output", "-o",
        choices=["console", "csv", "json", "all"],
        default="all",
        help="Output format (default: all)",
    )
    parser.add_argument(
        "--output-path",
        help="Output file path (for csv/json). Defaults to results/<timestamp>.<ext>",
    )
    args = parser.parse_args()

    # Load ground truth
    all_cases = _load_ground_truth()
    cases = _filter_cases(all_cases, args.product)

    print(f"\n{'='*70}")
    print(f"  PRICEFOX SINGLE PRODUCT EVAL PIPELINE")
    print(f"  Products: {len(cases)}")
    print(f"  Mode: {'eval-only (cached)' if args.eval_only else 'full (run + eval)'}")
    print(f"{'='*70}\n")

    # Step 1: Get reports (run agent or load cache)
    if args.eval_only:
        reports = load_cached_reports(cases)
    else:
        reports = asyncio.run(
            run_all(
                cases,
                base_url=args.api_url,
                concurrency=args.concurrency,
                force=args.force,
            )
        )

    if not reports:
        print("No reports available. Exiting.")
        sys.exit(1)

    # Step 2: Compute metrics
    print(f"\n{'='*70}")
    print("  COMPUTING METRICS")
    print(f"{'='*70}\n")

    all_metrics: list[dict] = []
    for tc in cases:
        test_id = tc["id"]
        report = reports.get(test_id, {"_eval_error": "Missing report"})
        m = compute_all_metrics(report, tc)
        all_metrics.append(m)

        error = m.get("_error")
        if error:
            print(f"  [{test_id}] ERROR: {error}")
        else:
            link_acc = m.get("offer_link_accuracy")
            link_acc_str = "-" if link_acc is None else f"{link_acc:.0%}"
            spu_acc = m.get("spu_model_accuracy")
            spu_acc_str = "-" if spu_acc is None else f"{spu_acc:.0%}"
            sku_spec_acc = m.get("sku_spec_display_accuracy")
            sku_spec_acc_str = "-" if sku_spec_acc is None else f"{sku_spec_acc:.0%}"
            price_acc = m.get("offer_price_accuracy")
            price_acc_str = "-" if price_acc is None else f"{price_acc:.0%}"
            ship_info_acc = m.get("shipping_info_accuracy")
            ship_info_acc_str = "-" if ship_info_acc is None else f"{ship_info_acc:.0%}"
            platform_svc_acc = m.get("platform_service_info_accuracy")
            platform_svc_acc_str = "-" if platform_svc_acc is None else f"{platform_svc_acc:.0%}"
            rebate_acc = m.get("rebate_info_accuracy")
            rebate_acc_str = "-" if rebate_acc is None else f"{rebate_acc:.0%}"
            kr4_val = m.get("kr4_3_platform_8_offer")
            if kr4_val is None:
                kr4_str = "-"
            else:
                kr4_str = "Y" if kr4_val else "N"
            top3_cov = m.get("kr4_1_top3_platform_coverage")
            top3_cov_str = "-" if top3_cov is None else f"{top3_cov:.0%}"
            top5_cnt = m.get("kr4_2_top5_platform_count")
            top5_cnt_str = "-" if top5_cnt is None else str(int(top5_cnt))
            top3_links = m.get("kr4_3_top3_link_count")
            top3_links_str = "-" if top3_links is None else str(int(top3_links))
            top5_links = m.get("kr4_4_top5_link_count")
            top5_links_str = "-" if top5_links is None else str(int(top5_links))
            kr45 = m.get("kr4_5_top3_link_completeness")
            kr45_str = "-" if kr45 is None else f"{kr45:.0%}"
            kr45_stats = m.get("_kr4_5_stats") or {}
            kr45_detail = ""
            if kr45_stats.get("matched_count") is not None and kr45_stats.get("crawler_unique_urls"):
                kr45_detail = (
                    f" ({kr45_stats['matched_count']}/{kr45_stats['crawler_unique_urls']})"
                )
            print(
                f"  [{test_id}] success={m.get('report_success')}  "
                f"duration={m.get('duration_minutes')}m  "
                f"key_info={'Y' if m.get('key_info_valid') else 'N'}  "
                f"link_acc={link_acc_str}  "
                f"spu_acc={spu_acc_str}  "
                f"sku_spec_acc={sku_spec_acc_str}  "
                f"price_acc={price_acc_str}  "
                f"ship_info_acc={ship_info_acc_str}  "
                f"platform_svc_acc={platform_svc_acc_str}  "
                f"rebate_acc={rebate_acc_str}  "
                f"kr4_3p8o={kr4_str}  "
                f"top3_cov={top3_cov_str}  "
                f"top5_cnt={top5_cnt_str}  "
                f"top3_links={top3_links_str}  "
                f"top5_links={top5_links_str}  "
                f"top3_link_complete={kr45_str}{kr45_detail}  "
                f"intent={m['intent_coverage']:.0%}/{m['intent_accuracy']:.0%}  "
                f"spec={m['spec_id_completeness']:.0%}/{m['spec_id_accuracy']:.0%}  "
                f"platforms={m['total_platform_count']}  "
                f"links={m['total_product_links']}  "
                f"reviews={'Y' if m.get('kr3_15_user_reviews') else 'N'}/"
                f"{'Y' if m.get('kr3_16_social_media') else 'N'}/"
                f"{'Y' if m.get('kr3_17_expert_reviews') else 'N'}/"
                f"{'Y' if m.get('kr3_18_attributes') else 'N'}"
            )

    # Step 3: Generate output
    print(f"\n{'='*70}")
    print("  RESULTS")
    print(f"{'='*70}\n")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.output in ("console", "all"):
        table = generate_console_table(all_metrics, cases)
        print(table)
        print()

    if args.output in ("csv", "all"):
        csv_path = args.output_path or str(RESULTS_DIR / f"eval_{timestamp}.csv")
        generate_csv(all_metrics, cases, output_path=csv_path)

    if args.output in ("json", "all"):
        json_path = args.output_path if args.output == "json" else str(
            RESULTS_DIR / f"eval_{timestamp}.json"
        )
        generate_json_report(all_metrics, cases, output_path=json_path)

    print(f"\n  Eval complete. {len(cases)} products evaluated.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
