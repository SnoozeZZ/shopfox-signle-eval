"""
Report generator: takes computed metrics for all products and outputs
console table + CSV matching the eval table format.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"

# Column definitions matching the eval table header order.
# Each tuple: (column_header, metric_key, format_type)
# format_type: "pct" = percentage, "int" = integer, "bool" = 0/1, "str" = string
COLUMNS = [
    ("型号", "_model", "str"),
    ("品类", "_category", "str"),
    ("报告成功率", "report_success", "str"),
    ("时长(分钟)", "duration_minutes", "num"),
    ("关键信息正确", "key_info_valid", "bool"),
    ("Offer链接指向准确率", "offer_link_accuracy", "pct"),
    ("SPU型号准确率", "spu_model_accuracy", "pct"),
    ("SKU规格展示正确率", "sku_spec_display_accuracy", "pct"),
    ("价格准确率", "offer_price_accuracy", "pct"),
    ("运费准确率", "shipping_info_accuracy", "pct"),
    ("平台服务信息准确率", "platform_service_info_accuracy", "pct"),
    ("返利板块信息准确率", "rebate_info_accuracy", "pct"),
    ("3平台8Offer达标", "kr4_3_platform_8_offer", "bool"),
    ("用户意图识别覆盖率", "intent_coverage", "pct"),
    ("用户意图识别准确率", "intent_accuracy", "pct"),
    ("规格信息识别完整%", "spec_id_completeness", "pct"),
    ("规格信息识别准确%", "spec_id_accuracy", "pct"),
    ("规格信息展示完整率", "spec_display_completeness", "pct"),
    ("top3平台覆盖率", "kr4_1_top3_platform_coverage", "pct"),
    ("top5平台数量", "kr4_2_top5_platform_count", "num"),
    ("覆盖平台数量", "total_platform_count", "num"),
    ("覆盖商品链接数量", "total_product_links", "int"),
    ("top3平台链接数量", "kr4_3_top3_link_count", "int"),
    ("top5平台链接数量", "kr4_4_top5_link_count", "int"),
    ("top3链接完整率", "kr4_5_top3_link_completeness", "pct"),
    ("是否提供用户评论信息", "kr3_15_user_reviews", "bool"),
    ("是否提供社媒信息", "kr3_16_social_media", "bool"),
    ("是否提供专家测评信息", "kr3_17_expert_reviews", "bool"),
    ("是否提供属性信息", "kr3_18_attributes", "bool"),
]


def _fmt(value: Any, fmt_type: str) -> str:
    """Format a metric value for display."""
    if value is None:
        return "-"
    if fmt_type == "pct":
        return f"{value * 100:.0f}%"
    if fmt_type == "bool":
        return "1" if value else "0"
    if fmt_type in ("int", "num"):
        return str(int(value)) if value is not None else "-"
    return str(value)


def _compute_summary_row(all_metrics: list[dict], test_cases: list[dict]) -> dict:
    """Compute the summary (average) row across all products."""
    summary: dict[str, Any] = {"_model": "AVERAGE", "_category": "-"}

    pct_keys = [k for _, k, fmt in COLUMNS if fmt == "pct"]
    int_keys = [k for _, k, fmt in COLUMNS if fmt in ("int", "num")]
    bool_keys = [k for _, k, fmt in COLUMNS if fmt == "bool"]

    for key in pct_keys:
        vals = [m[key] for m in all_metrics if m.get(key) is not None]
        summary[key] = sum(vals) / len(vals) if vals else None

    for key in int_keys:
        vals = [m[key] for m in all_metrics if m.get(key) is not None]
        summary[key] = sum(vals) / len(vals) if vals else None

    for key in bool_keys:
        vals = [m[key] for m in all_metrics if m.get(key) is not None]
        summary[key] = sum(1 for v in vals if v) if vals else None

    return summary


def generate_console_table(
    all_metrics: list[dict],
    test_cases: list[dict],
) -> str:
    """Generate a formatted console table string."""
    summary = _compute_summary_row(all_metrics, test_cases)

    # Build rows
    rows: list[dict] = [summary]
    for tc, m in zip(test_cases, all_metrics):
        row = dict(m)
        row["_model"] = tc["model"]
        row["_category"] = tc["category"]
        rows.append(row)

    # Compute column widths
    headers = [c[0] for c in COLUMNS]
    col_widths = [len(h) for h in headers]

    formatted_rows: list[list[str]] = []
    for row in rows:
        cells = []
        for i, (_, key, fmt) in enumerate(COLUMNS):
            cell = _fmt(row.get(key), fmt)
            cells.append(cell)
            col_widths[i] = max(col_widths[i], len(cell))
        formatted_rows.append(cells)

    # Build output
    lines: list[str] = []
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    # Header
    lines.append(sep)
    header_line = "|" + "|".join(
        f" {h:<{col_widths[i]}} " for i, h in enumerate(headers)
    ) + "|"
    lines.append(header_line)
    lines.append(sep)

    # Summary row
    summary_cells = formatted_rows[0]
    summary_line = "|" + "|".join(
        f" {c:<{col_widths[i]}} " for i, c in enumerate(summary_cells)
    ) + "|"
    lines.append(summary_line)
    lines.append(sep)

    # Data rows
    for cells in formatted_rows[1:]:
        line = "|" + "|".join(
            f" {c:<{col_widths[i]}} " for i, c in enumerate(cells)
        ) + "|"
        lines.append(line)

    lines.append(sep)
    return "\n".join(lines)


def generate_csv(
    all_metrics: list[dict],
    test_cases: list[dict],
    output_path: str | Path | None = None,
) -> str:
    """Generate CSV content and optionally write to file."""
    summary = _compute_summary_row(all_metrics, test_cases)

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header
    writer.writerow([c[0] for c in COLUMNS])

    # Summary row
    writer.writerow([_fmt(summary.get(key), fmt) for _, key, fmt in COLUMNS])

    # Data rows
    for tc, m in zip(test_cases, all_metrics):
        row_data: list[str] = []
        for _, key, fmt in COLUMNS:
            if key == "_model":
                row_data.append(tc["model"])
            elif key == "_category":
                row_data.append(tc["category"])
            else:
                row_data.append(_fmt(m.get(key), fmt))
        writer.writerow(row_data)

    content = buf.getvalue()

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8-sig")  # BOM for Excel compatibility
        print(f"  CSV written to: {path}")

    return content


def generate_json_report(
    all_metrics: list[dict],
    test_cases: list[dict],
    output_path: str | Path | None = None,
) -> dict:
    """Generate a structured JSON report with all metrics."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "num_products": len(test_cases),
        "summary": _compute_summary_row(all_metrics, test_cases),
        "products": [],
    }

    for tc, m in zip(test_cases, all_metrics):
        entry = {
            "id": tc["id"],
            "model": tc["model"],
            "category": tc["category"],
            "metrics": m,
        }
        report["products"].append(entry)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  JSON report written to: {path}")

    return report
