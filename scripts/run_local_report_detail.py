#!/usr/bin/env python3
"""
本地跑单份/多份报告评测，输出带中文名的指标明细与综合分拆解。

直接复用 compute_all_metrics + compute_composite_score，不触发 external-callback。

用法:
    python scripts/run_local_report_detail.py input/report_xxx.json
    python scripts/run_local_report_detail.py input/report_a.json input/report_b.json
    python scripts/run_local_report_detail.py --output-dir output/local_eval input/report_xxx.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from SingleProductEval.config import (  # noqa: E402
    CALLBACK_ISSUE_SOURCE_MAP,
    CALLBACK_METRIC_VALUE_FALLBACK,
    COMPOSITE_SCORE_WEIGHT,
)
from SingleProductEval.eval_job_service import (  # noqa: E402
    build_gt_from_submit,
    persist_job_files,
    public_metrics,
)
from SingleProductEval.metrics import compute_all_metrics  # noqa: E402
from SingleProductEval.report_composite_score import (  # noqa: E402
    compute_composite_score,
    inject_composite_into_raw_metrics,
)

# ── 指标中文名（对齐 docs/METRICS.md 表 A/B 与 report_generator.COLUMNS）──────

METRIC_NAMES_CN: dict[str, str] = {
    # 回调业务指标
    "report_success": "报告是否成功",
    "duration_minutes": "耗时（分钟）",
    "key_info_valid": "关键板块有效",
    "intent_coverage": "意图覆盖率",
    "intent_accuracy": "意图准确率",
    "offer_link_accuracy": "链接指向准确率",
    "spu_model_accuracy": "SPU 机型准确率",
    "sku_spec_display_accuracy": "SKU 规格展示准确率",
    "offer_price_accuracy": "价格准确率",
    "shipping_info_accuracy": "运费准确率",
    "rebate_info_accuracy": "返利/优惠券准确率",
    "has_user_reviews": "有用户评论",
    "has_social_media": "有社媒反馈",
    "has_expert_reviews": "有专家评测",
    "has_attributes": "有属性/规格",
    "platform_service_info_accuracy": "平台服务信息准确率",
    "kr4_3_platform_8_offer": "3 平台 8 offer",
    "top3_platform_coverage": "Top3 平台覆盖率",
    "top5_platform_count": "Top5 平台覆盖数",
    "top3_link_count": "Top3 链接数",
    "top5_link_count": "Top5 链接数",
    "kr4_5_top3_link_completeness": "Top3 链接完备率",
    # 综合分维度（档位分 + 贡献分）
    "eval_dim_platform_count_score": "平台数量档位分",
    "eval_dim_platform_count_contrib": "平台数量贡献分",
    "eval_dim_offer_count_score": "Offer 数量档位分",
    "eval_dim_offer_count_contrib": "Offer 数量贡献分",
    "eval_dim_offer_info_accuracy_score": "Offer 信息准确率档位分",
    "eval_dim_offer_info_accuracy_contrib": "Offer 信息准确率贡献分",
    "eval_dim_product_info_accuracy_score": "商品信息准确率档位分",
    "eval_dim_product_info_accuracy_contrib": "商品信息准确率贡献分",
    "eval_dim_section_completeness_score": "版块完整率档位分",
    "eval_dim_section_completeness_contrib": "版块完整率贡献分",
    "eval_final_score": "综合最终分",
    # 内部指标（不进回调）
    "spec_id_completeness": "规格识别完整度",
    "spec_id_accuracy": "规格识别准确度",
    "spec_display_completeness": "规格展示完整度",
    "total_platform_count": "平台总数",
    "total_product_links": "商品链接总数",
    # canonical 别名（raw_metrics 内可能出现）
    "kr4_1_top3_platform_coverage": "Top3 平台覆盖率",
    "kr4_2_top5_platform_count": "Top5 平台覆盖数",
    "kr4_3_top3_link_count": "Top3 链接数",
    "kr4_4_top5_link_count": "Top5 链接数",
    "kr3_15_user_reviews": "有用户评论",
    "kr3_16_social_media": "有社媒反馈",
    "kr3_17_expert_reviews": "有专家评测",
    "kr3_18_attributes": "有属性/规格",
}

# 控制台分组展示顺序
METRIC_GROUPS: list[tuple[str, list[str]]] = [
    ("运行指标", ["report_success", "duration_minutes"]),
    ("关键信息", [
        "key_info_valid",
        "offer_link_accuracy",
        "spu_model_accuracy",
        "sku_spec_display_accuracy",
        "offer_price_accuracy",
        "shipping_info_accuracy",
        "platform_service_info_accuracy",
        "rebate_info_accuracy",
    ]),
    ("意图识别", ["intent_coverage", "intent_accuracy"]),
    ("规格识别/展示", [
        "spec_id_completeness",
        "spec_id_accuracy",
        "spec_display_completeness",
    ]),
    ("平台覆盖", [
        "kr4_3_platform_8_offer",
        "top3_platform_coverage",
        "top5_platform_count",
        "top3_link_count",
        "top5_link_count",
        "kr4_5_top3_link_completeness",
        "total_platform_count",
        "total_product_links",
    ]),
    ("内容板块", [
        "has_user_reviews",
        "has_social_media",
        "has_expert_reviews",
        "has_attributes",
    ]),
    ("综合分", [
        "eval_dim_platform_count_score",
        "eval_dim_platform_count_contrib",
        "eval_dim_offer_count_score",
        "eval_dim_offer_count_contrib",
        "eval_dim_offer_info_accuracy_score",
        "eval_dim_offer_info_accuracy_contrib",
        "eval_dim_product_info_accuracy_score",
        "eval_dim_product_info_accuracy_contrib",
        "eval_dim_section_completeness_score",
        "eval_dim_section_completeness_contrib",
        "eval_final_score",
    ]),
]

# issue 内部键 (_kr3_8_issues ...) → 回调 krId (offer_link_accuracy ...)
ISSUE_KEY_TO_METRIC: dict[str, str] = dict(CALLBACK_ISSUE_SOURCE_MAP)

COMPOSITE_DIM_CN: dict[str, str] = {
    "platform_count": "平台数量",
    "offer_count": "Offer 数量",
    "offer_info_accuracy": "Offer 信息准确率（链接∩价格）",
    "product_info_accuracy": "商品信息准确率（图片+规格）",
    "section_completeness": "版块完整率",
}

SECTION_CN: dict[str, str] = {
    "coupon": "优惠码",
    "rebate": "返利",
    "reviews": "用户评论",
    "social_media": "社媒",
    "expert_reviews": "专家测评",
    "attributes": "属性/规格",
}

COMPOSITE_TIER_HINT = """  综合分档位说明:
  · 平台数: >=5->100, 4->80, 3->60, 2->20, 1->0
  · Offer数: >=15->100, 10-14->70, 8-9->50, 5-7->50, <5->0
  · 准确率: 100%->100, >=90%->80, >=80%->60, <80%->0
  · 商品信息: 图片通过且规格100%->100, 否则->0
  · 版块完整: 6/6->100, >=80%->50, >=65%->20, <65%->0
  · 每项权重 0.2，理论最高 100 分"""


def _cn(metric_id: str) -> str:
    return METRIC_NAMES_CN.get(metric_id, metric_id)


def _resolve_value(raw: dict[str, Any], metric_id: str) -> Any:
    if metric_id in raw:
        return raw[metric_id]
    alt = CALLBACK_METRIC_VALUE_FALLBACK.get(metric_id)
    if alt and alt in raw:
        return raw[alt]
    return None


def _fmt_value(value: Any) -> str:
    if value is None:
        return "—（未算出）"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        if 0.0 <= value <= 1.0 and value != int(value):
            return f"{value * 100:.1f}%"
        return f"{value:.2f}"
    return str(value)


def _extract_report_id(path: Path) -> str:
    m = re.search(
        r"report_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        path.stem,
        re.I,
    )
    return m.group(1) if m else path.stem


def _search_term(report: dict[str, Any]) -> str:
    spu = report.get("spu_metadata") or {}
    return (
        str(spu.get("original_query") or "").strip()
        or str(report.get("name") or "").strip()
        or "local-eval"
    )


def _collect_issues(raw_metrics: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for issue_key, metric_id in ISSUE_KEY_TO_METRIC.items():
        items = raw_metrics.get(issue_key) or []
        for item in items:
            if isinstance(item, str):
                issues.append({
                    "metric_id": metric_id,
                    "metric_cn": _cn(metric_id),
                    "description": item,
                })
            elif isinstance(item, dict):
                issues.append({
                    "metric_id": metric_id,
                    "metric_cn": _cn(metric_id),
                    **item,
                })
    return issues


def _print_header(title: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")


def _print_metrics(raw_metrics: dict[str, Any]) -> None:
    _print_header("指标明细")
    for group_name, ids in METRIC_GROUPS:
        print(f"\n【{group_name}】")
        for mid in ids:
            val = _resolve_value(raw_metrics, mid)
            print(f"  · {_cn(mid)} ({mid}): {_fmt_value(val)}")


def _print_composite(composite: dict[str, Any]) -> None:
    _print_header("综合分拆解（五维 × 权重 0.2）")
    final = composite.get("eval_final_score")
    max_score = composite.get("eval_max_score", 100)
    print(f"  综合最终分: {final} / {max_score}\n")
    print(COMPOSITE_TIER_HINT)

    dims = composite.get("dimensions") or {}
    total_contrib = 0.0
    print(f"\n  {'维度':<30}{'原始值':<16}{'档位分':>7}{'权重':>7}{'贡献分':>9}")
    print(f"  {'-' * 70}")

    for dim_id, dim_cn in COMPOSITE_DIM_CN.items():
        d = dims.get(dim_id) or {}
        raw = d.get("raw")
        score = d.get("score", 0)
        weight = d.get("weight", COMPOSITE_SCORE_WEIGHT)
        contrib = d.get("contribution")
        if contrib is None:
            contrib = round(score * weight, 1)
        total_contrib += contrib

        raw_str = _fmt_value(raw)
        if dim_id == "offer_info_accuracy" and d.get("degraded"):
            raw_str += "(降级:仅链接)"
        print(f"  {dim_cn:<30}{raw_str:<16}{score:>7}{weight:>7.1f}{contrib:>9.1f}")

        if dim_id == "section_completeness":
            sections = d.get("sections") or {}
            present = d.get("present")
            sec_detail = "  ".join(
                f"{SECTION_CN.get(k, k)}={'✓' if v else '✗'}"
                for k, v in sections.items()
            )
            print(f"      6 版块({present}/6): {sec_detail}")

    print(f"  {'-' * 70}")
    print(f"  {'合计':<30}{'':<16}{'':>7}{'':>7}{round(total_contrib, 1):>9.1f}")


def _print_issues(issues: list[dict[str, Any]], limit: int) -> None:
    shown = min(len(issues), limit)
    _print_header(f"Issues 明细（共 {len(issues)} 条，展示前 {shown} 条）")
    if not issues:
        print("  （无 issues）")
        return
    for i, issue in enumerate(issues[:limit], 1):
        metric_cn = issue.get("metric_cn", "")
        reason = issue.get("reason", "")
        desc = issue.get("description") or issue.get("detail") or ""
        url = issue.get("url") or issue.get("link") or ""
        retailer = issue.get("retailer", "")
        line = f"  {i}. [{metric_cn}]"
        if reason:
            line += f" reason={reason}"
        if retailer:
            line += f" · {retailer}"
        print(line)
        if desc:
            print(f"     {desc}")
        if url:
            print(f"     {url}")
    if len(issues) > limit:
        print(f"  ... 还有 {len(issues) - limit} 条，见输出 JSON")


def eval_one_report(
    report_path: Path,
    *,
    run_id: str | None = None,
    save_job: bool = True,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report_id = _extract_report_id(report_path)
    search_term = _search_term(report)
    run_id = run_id or f"local-{report_id[:8]}-{uuid.uuid4().hex[:6]}"

    gt, gt_warnings = build_gt_from_submit(search_term, report, run_id, report_id)
    raw_metrics = compute_all_metrics(report, gt, enabled_metrics=None)
    composite = compute_composite_score(report, gt, raw_metrics)
    inject_composite_into_raw_metrics(raw_metrics, composite)
    metrics_out = public_metrics(raw_metrics)
    issues = _collect_issues(raw_metrics)

    result_doc: dict[str, Any] = {
        "runId": run_id,
        "reportId": report_id,
        "searchTerm": search_term,
        "sourceFile": str(report_path),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "gt_warnings": gt_warnings,
        "metrics": metrics_out,
        "raw_metrics": raw_metrics,
        "composite_score": composite,
        "issues_summary": issues,
    }

    if save_job:
        persist_job_files(
            run_id,
            submit={
                "reportId": report_id,
                "runId": run_id,
                "searchTerm": search_term,
                "sourceFile": str(report_path),
            },
            gt=gt,
            result=result_doc,
        )

    return result_doc


def main() -> int:
    parser = argparse.ArgumentParser(description="本地跑报告评测明细（中文输出）")
    parser.add_argument(
        "reports",
        nargs="+",
        type=Path,
        help="报告 JSON 路径，如 input/report_xxx.json",
    )
    parser.add_argument("--run-id", help="自定义 run_id（仅对第一个文件生效，其余自动生成）")
    parser.add_argument("--output-dir", type=Path, help="额外保存 detail JSON 的目录")
    parser.add_argument(
        "--no-save-job",
        action="store_true",
        help="不写入 SingleProductEval/eval_logs/backend_jobs",
    )
    parser.add_argument(
        "--issue-limit",
        type=int,
        default=30,
        help="控制台最多展示 issues 条数（默认 30）",
    )
    args = parser.parse_args()

    for idx, path in enumerate(args.reports):
        if not path.exists():
            print(f"文件不存在: {path}", file=sys.stderr)
            return 1

        print(f"\n\n{'#' * 72}")
        print(f"# 评测报告: {path.name}")
        print(f"{'#' * 72}")

        result = eval_one_report(
            path,
            run_id=args.run_id if idx == 0 else None,
            save_job=not args.no_save_job,
        )

        print(f"  商品/搜索词: {result['searchTerm']}")
        print(f"  report_id:   {result['reportId']}")
        print(f"  run_id:      {result['runId']}")
        if result.get("gt_warnings"):
            print(f"  GT 警告:     {', '.join(result['gt_warnings'])}")

        _print_metrics(result["raw_metrics"])
        _print_composite(result["composite_score"])
        _print_issues(result["issues_summary"], limit=args.issue_limit)

        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            out_path = args.output_dir / f"{result['runId']}_detail.json"
            out_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\n  明细 JSON 已保存: {out_path}")

        if not args.no_save_job:
            print(
                f"\n  标准结果已保存: "
                f"SingleProductEval/eval_logs/backend_jobs/{result['runId']}/result.json"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
