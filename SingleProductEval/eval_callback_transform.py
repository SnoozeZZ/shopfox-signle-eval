"""
Transform raw_metrics into backend external-callback payload.

POST /v1/eval/runs/external-callback
krId and attributionKr use backend contract ids (CALLBACK_METRIC_IDS).
"""

from __future__ import annotations

from typing import Any

from .config import (
    CALLBACK_ISSUE_EXCLUDE_REASONS,
    CALLBACK_ISSUE_SOURCE_MAP,
    CALLBACK_ISSUES_MAX,
    CALLBACK_METRIC_IDS,
    CALLBACK_METRIC_VALUE_FALLBACK,
    METRICS_REGISTRY,
)

_METRIC_TYPE_BY_ID: dict[str, str] = {m["id"]: m["type"] for m in METRICS_REGISTRY}

_P0_REASONS = frozenset({
    "price_mismatch",
    "dead_link",
    "redirect_to_listing",
    "listing_page_url",
    "missing_in_report",
})


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _metric_result(metric_id: str, value: Any) -> dict[str, Any]:
    return {
        "krId": metric_id,
        "value": _format_value(value),
        "valueType": _METRIC_TYPE_BY_ID.get(metric_id, "string"),
        "passed": value is not None,
        "reason": "",
    }


def _resolve_metric_value(metric_id: str, raw_metrics: dict[str, Any]) -> Any:
    if metric_id in raw_metrics:
        return raw_metrics[metric_id]
    fallback_key = CALLBACK_METRIC_VALUE_FALLBACK.get(metric_id)
    if fallback_key:
        return raw_metrics.get(fallback_key)
    return None


def _build_metrics_array(
    raw_metrics: dict[str, Any],
    enabled_metrics: list[str] | None,
) -> list[dict[str, Any]]:
    del enabled_metrics  # callback metrics are fixed; rubric toggle does not change krId set
    return [
        _metric_result(metric_id, _resolve_metric_value(metric_id, raw_metrics))
        for metric_id in CALLBACK_METRIC_IDS
    ]


def _truncate(text: str, limit: int = 500) -> str:
    return text[:limit] if text else ""


def _format_price(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        num = float(value)
        if num == int(num):
            return f"${int(num)}"
        return f"${num:.2f}"
    text = str(value).strip()
    if text.startswith("$"):
        return text
    return f"${text}"


def _context_suffix(name: str, retailer: str) -> str:
    parts = [p for p in (name.strip(), retailer.strip()) if p]
    if not parts:
        return ""
    return f" ({' · '.join(parts)})"


def _describe_dict_issue_fallback(issue: dict[str, Any]) -> str:
    parts: list[str] = []
    for label, field in (
        ("retailer", "retailer"),
        ("reason", "reason"),
        ("model", "offer_model"),
        ("product_model", "product_model"),
        ("name", "product_name"),
        ("detail", "detail"),
    ):
        val = issue.get(field)
        if val:
            parts.append(f"{label}={val}")
    return "; ".join(parts) if parts else str(issue)


def _describe_offer_price(issue: dict[str, Any]) -> str:
    recorded = _format_price(issue.get("recorded_price"))
    crawled = _format_price(issue.get("crawled_price"))
    retailer = str(issue.get("retailer") or "")
    name = str(issue.get("product_name") or "")
    if recorded and crawled:
        body = f"Card shows {recorded}, landing page {crawled}"
    else:
        body = _describe_dict_issue_fallback(issue)
    return _truncate(body + _context_suffix(name, retailer))


def _describe_offer_link(issue: dict[str, Any]) -> str:
    retailer = str(issue.get("retailer") or "Unknown")
    reason = str(issue.get("reason") or "")
    detail = str(issue.get("detail") or "")
    name = str(issue.get("product_name") or "").strip()

    if reason == "dead_link":
        extra = f" ({detail})" if detail else ""
        text = f"{retailer} link invalid{extra}"
    elif reason == "listing_page_url":
        text = f"{retailer} link points to listing page, not product detail"
    elif reason == "redirect_to_listing":
        text = f"{retailer} redirects to listing page"
        if detail:
            text += f" ({detail[:120]})"
    elif reason == "missing_or_invalid_url":
        text = f"{retailer} offer missing valid product URL"
    elif reason == "not_target_product":
        text = f"{retailer} link is not the target product"
    elif reason == "url_class_unknown":
        text = f"{retailer} URL could not be classified as product detail"
    else:
        text = f"{retailer}: {reason or 'link issue'}"
        if detail:
            text += f" ({detail[:120]})"

    if name:
        text = f"{name} — {text}"
    return _truncate(text)


def _describe_spu_model(issue: dict[str, Any]) -> str:
    user_model = str(issue.get("user_model") or "")
    shown = str(issue.get("product_name") or issue.get("offer_model") or "")
    retailer = str(issue.get("retailer") or "")
    reason = str(issue.get("reason") or "")

    if reason == "empty_model":
        text = f"{retailer} offer has empty product model"
    elif user_model and shown:
        text = f"Search {user_model}, shows {shown}"
        if retailer:
            text += f" ({retailer})"
    elif user_model:
        text = f"Search {user_model}, model mismatch ({retailer})"
    else:
        detail = str(issue.get("detail") or "")
        text = _describe_dict_issue_fallback(issue)
        if detail and detail not in text:
            text = f"{text}; {detail}"

    return _truncate(text)


def _describe_sku_spec(issue: dict[str, Any]) -> str:
    retailer = str(issue.get("retailer") or "")
    reason = str(issue.get("reason") or "")
    dim = str(issue.get("failed_dimension") or "")
    offer_specs = issue.get("offer_specs") if isinstance(issue.get("offer_specs"), dict) else {}
    expected = str(offer_specs.get(dim) or "") if dim else ""
    display = str(issue.get("display_condition") or "")

    if reason == "spec_missing" and dim:
        text = f"{retailer}: missing spec dimension {dim}"
    elif reason == "display_field_missing" and dim:
        text = f"{retailer}: missing display field for {dim}"
    elif reason == "display_inconsistent" and dim:
        text = (
            f"{retailer}: {dim} inconsistent "
            f"(variant={expected}, display={display or 'missing'})"
        )
    elif dim and expected:
        text = f"{retailer}: {dim}={expected} spec mismatch"
    else:
        text = f"{retailer}: {reason or 'spec mismatch'}"
        if dim:
            text += f" ({dim})"

    return _truncate(text)


def _describe_rebate(issue: dict[str, Any]) -> str:
    source = str(issue.get("source") or "")
    retailer = str(issue.get("retailer") or "")
    claim_type = str(issue.get("type") or issue.get("category") or "").lower()
    prefix = "Coupon: " if claim_type == "coupon" else ""
    reason = str(issue.get("reason") or "")
    desc = str(issue.get("description") or "")[:120]
    claimed = issue.get("claimed_rate")
    found = issue.get("found_rate")

    ctx = " · ".join(p for p in (source, retailer) if p)

    if reason == "rate_mismatch" and claimed is not None and found is not None:
        text = f"{prefix}Report {claimed}%, page {found}%"
    elif reason == "description_mismatch" and desc:
        text = f"{prefix}Report \"{desc}\", does not match page"
    elif reason in ("link_source_host_mismatch", "link_retailer_mismatch"):
        text = f"{prefix}{source or retailer} link does not match retailer"
    elif reason == "tier_not_found":
        text = f"{prefix}{source or retailer}: rebate tier not found on page"
    elif reason == "llm_mismatch":
        llm_reason = str(issue.get("llm_reason") or "")
        text = f"{prefix}Rebate claim mismatch"
        if llm_reason:
            text += f" ({llm_reason[:100]})"
    elif reason == "category_mismatch":
        text = f"{prefix}Category mismatch on {ctx or 'rebate page'}"
    elif reason == "field_inconsistent":
        text = f"{prefix}Rebate fields inconsistent ({ctx})"
    else:
        text = f"{prefix}{reason or 'rebate mismatch'}"
        if ctx:
            text += f" ({ctx})"

    return _truncate(text)


def _describe_shipping(issue: dict[str, Any]) -> str:
    retailer = str(issue.get("retailer") or "")
    reason = str(issue.get("reason") or "")
    cost = str(issue.get("shippingCost") or "").strip()

    if reason == "field_missing":
        text = f"Missing shipping cost on {retailer}"
    elif cost:
        text = f"Shipping issue on {retailer}: {cost}"
    else:
        text = f"Shipping issue on {retailer}: {reason or 'invalid'}"
    return _truncate(text)


def _describe_platform_service(issue: dict[str, Any]) -> str:
    retailer = str(issue.get("retailer") or "")
    reason = str(issue.get("reason") or "")
    shipping = str(issue.get("shippingTime") or "").strip()
    returns = str(issue.get("returnPolicy") or "").strip()

    if reason == "field_missing":
        field = str(issue.get("failed_field") or "")
        if field == "returnPolicy":
            text = f"Missing return policy on {retailer}"
        elif field == "shippingTime":
            text = f"Missing delivery time on {retailer}"
        else:
            text = f"Missing platform service field on {retailer}"
    elif reason == "delivery_unreasonable":
        text = f"Unreasonable delivery time on {retailer}: {shipping}"
    else:
        text = f"Platform service issue on {retailer}: {reason}"
        if shipping or returns:
            text += f" (ship={shipping[:40]}, return={returns[:40]})"
    return _truncate(text)


def _describe_kr4_5(issue: dict[str, Any]) -> str:
    platform = str(issue.get("platform") or "")
    name = str(issue.get("product_name") or "")
    text = f"Top3 reference missing in report: {platform} {name}".strip()
    return _truncate(text)


def _describe_issue(attribution_kr: str, issue: dict[str, Any]) -> str:
    describers = {
        "offer_price_accuracy": _describe_offer_price,
        "offer_link_accuracy": _describe_offer_link,
        "spu_model_accuracy": _describe_spu_model,
        "sku_spec_display_accuracy": _describe_sku_spec,
        "rebate_info_accuracy": _describe_rebate,
        "shipping_info_accuracy": _describe_shipping,
        "platform_service_info_accuracy": _describe_platform_service,
        "kr4_5_top3_link_completeness": _describe_kr4_5,
    }
    fn = describers.get(attribution_kr)
    if fn:
        return fn(issue)
    return _truncate(_describe_dict_issue_fallback(issue))


def _issue_priority(attribution_kr: str, issue: dict[str, Any]) -> str:
    reason = str(issue.get("reason") or "")
    if reason in _P0_REASONS:
        return "P0"
    return "P1"


def _kr3_1_section(text: str) -> str:
    lower = text.lower()
    if "pricecomparison" in lower:
        return "priceComparison"
    return "spec"


def _kr3_1_priority(text: str) -> str:
    lower = text.lower()
    if "missing url" in lower or "pricecomparison missing" in lower:
        return "P0"
    return "P1"


def _should_skip_dict_issue(issue: dict[str, Any]) -> bool:
    reason = str(issue.get("reason") or "")
    if reason in CALLBACK_ISSUE_EXCLUDE_REASONS:
        return True
    if str(issue.get("outcome") or "") == "unverifiable":
        return True
    return False


def _issue_entry(
    attribution_kr: str,
    description: str,
    *,
    priority: str = "P1",
    section: str = "",
    link: str = "",
) -> dict[str, str]:
    return {
        "attributionKr": attribution_kr,
        "description": description[:500],
        "priority": priority,
        "section": section,
        "link": link,
    }


def _collect_issues(raw_metrics: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    for raw_key, attribution_kr in CALLBACK_ISSUE_SOURCE_MAP.items():
        items = raw_metrics.get(raw_key)
        if not items:
            continue
        if raw_key == "_kr3_1_issues":
            for item in items:
                if isinstance(item, str) and item.strip():
                    text = item.strip()
                    issues.append(
                        _issue_entry(
                            attribution_kr,
                            text,
                            priority=_kr3_1_priority(text),
                            section=_kr3_1_section(text),
                        )
                    )
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if _should_skip_dict_issue(item):
                continue
            issues.append(
                _issue_entry(
                    attribution_kr,
                    _describe_issue(attribution_kr, item),
                    priority=_issue_priority(attribution_kr, item),
                    section=str(item.get("section") or "priceComparison"),
                    link=str(item.get("url") or ""),
                )
            )

    return issues[:CALLBACK_ISSUES_MAX]


def build_external_callback_payload(
    *,
    run_id: str,
    report_id: str,
    search_term: str,
    raw_metrics: dict[str, Any],
    enabled_metrics: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "runId": run_id,
        "reportId": report_id,
        "searchTerm": search_term,
        "metrics": _build_metrics_array(raw_metrics, enabled_metrics),
        "issues": _collect_issues(raw_metrics),
    }
