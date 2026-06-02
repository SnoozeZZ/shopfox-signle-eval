"""
KR3-9 validators: SPU model scope accuracy (user model vs offer model + title).

Rule layer: norm(product_model) == norm(user_model) only.
All other offers are judged by LLM (model + title together).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from .config import KR3_9_LLM_BATCH_SIZE, KR3_9_LLM_MAX_RETRIES, KR3_9_LLM_MODEL, KR3_9_USE_LLM
from .llm_client import chat_json, has_dashscope_api_key

OfferRoute = Literal["exact_match", "empty_mismatch", "needs_llm"]

_INVALID_MODEL_VALUES = frozenset({"", "n/a", "na", "none", "null", "unknown"})

_LLM_SYSTEM_PROMPT = """You are a product model matching evaluator for e-commerce offers.
Given a user's target product model and a list of offers (each with product_model and product_name/title),
decide whether each offer refers to the SAME product SPU as the user requested.

Rules:
- Consider BOTH product_model and product_name together.
- A numeric product_model (e.g. 19080) may be a manufacturer style number; use the title if it identifies the user model.
- Different variants or sub-models are NOT a match (e.g. user wants "Leica Q3" but offer is "Q3 43", "Q3 Monochrome", "iPhone Air Mini" vs "iPhone Air").
- Sub-model suffixes like Mini, Ultra, Plus, Pro Max, 43, Monochrome indicate a different SPU unless the user explicitly requested that variant.
- Accessories, bundles for other products, or clearly different models are NOT a match.

Respond with ONLY a JSON array, no markdown:
[{"index": 0, "match": true, "reason": "brief explanation"}, ...]
"""


def derive_user_model(report: dict, gt: dict) -> str:
    for key in ("user_model", "search_term"):
        val = gt.get(key)
        if val and str(val).strip():
            return str(val).strip()

    for src in (
        report.get("query"),
        (report.get("spu_metadata") or {}).get("original_query"),
        report.get("name"),
    ):
        if src and str(src).strip():
            return str(src).strip()

    return ""


def _norm(text: str) -> str:
    return re.sub(r"[\s\-_.]+", "", str(text or "").lower())


def _is_invalid_model(text: str) -> bool:
    return str(text or "").strip().lower() in _INVALID_MODEL_VALUES


def _is_exact_model_match(product_model: str, user_model: str) -> bool:
    pm, um = _norm(product_model), _norm(user_model)
    return bool(pm and um and pm == um)


def _is_empty_offer(product_model: str, product_name: str) -> bool:
    return _is_invalid_model(product_model) and not str(product_name or "").strip()


def _route_offer(offer: dict, user_model: str) -> OfferRoute:
    product_model = str(offer.get("product_model") or "").strip()
    product_name = str(offer.get("product_name") or "").strip()

    if _is_exact_model_match(product_model, user_model):
        return "exact_match"
    if _is_empty_offer(product_model, product_name):
        return "empty_mismatch"
    return "needs_llm"


def _make_issue(
    index: int,
    offer: dict,
    user_model: str,
    reason: str,
    match_method: str,
    detail: str | None = None,
) -> dict:
    issue = {
        "index": index,
        "retailer": str(offer.get("retailer") or ""),
        "user_model": user_model,
        "offer_model": str(offer.get("product_model") or ""),
        "product_name": str(offer.get("product_name") or "")[:200],
        "reason": reason,
        "match_method": match_method,
        "section": "priceComparison",
    }
    if detail:
        issue["detail"] = detail
    return issue


def _llm_judge_batch(user_model: str, batch: list[tuple[int, dict]]) -> dict[int, tuple[bool, str]]:
    payload = {
        "user_model": user_model,
        "offers": [
            {
                "index": idx,
                "retailer": offer.get("retailer", ""),
                "product_model": offer.get("product_model", ""),
                "product_name": offer.get("product_name", ""),
            }
            for idx, offer in batch
        ],
    }
    user_msg = json.dumps(payload, ensure_ascii=False)
    results = chat_json(_LLM_SYSTEM_PROMPT, user_msg, model=KR3_9_LLM_MODEL, enable_thinking=False)

    if isinstance(results, dict):
        results = results.get("results") or results.get("offers") or [results]

    parsed: dict[int, tuple[bool, str]] = {}
    if not isinstance(results, list):
        raise ValueError("LLM response is not a JSON array")

    for item in results:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if idx is None:
            continue
        parsed[int(idx)] = (bool(item.get("match")), str(item.get("reason") or ""))

    return parsed


def validate_spu_model_scope(
    report: dict,
    gt: dict,
    offers: list[dict] | None = None,
) -> tuple[float | None, list[dict], str, list[str]]:
    """
    Returns (accuracy, issues, user_model, warnings).
    """
    user_model = derive_user_model(report, gt)
    warnings: list[str] = []

    if not offers:
        return None, [], user_model, warnings

    if not user_model:
        warnings.append("kr3_9: no user_model derived")
        return None, [], user_model, warnings

    issues: list[dict] = []
    correct_flags: dict[int, bool] = {}
    llm_queue: list[tuple[int, dict]] = []

    for i, offer in enumerate(offers):
        route = _route_offer(offer, user_model)
        if route == "exact_match":
            correct_flags[i] = True
        elif route == "empty_mismatch":
            correct_flags[i] = False
            issues.append(_make_issue(i, offer, user_model, "empty_model", "rule"))
        else:
            llm_queue.append((i, offer))

    use_llm = KR3_9_USE_LLM and has_dashscope_api_key()
    if llm_queue and not use_llm:
        warnings.append(
            f"kr3_9: LLM required for {len(llm_queue)} offers but unavailable; accuracy not computed"
        )
        return None, issues, user_model, warnings

    if llm_queue and use_llm:
        max_attempts = KR3_9_LLM_MAX_RETRIES + 1
        for start in range(0, len(llm_queue), KR3_9_LLM_BATCH_SIZE):
            batch = llm_queue[start : start + KR3_9_LLM_BATCH_SIZE]
            try:
                llm_results = _llm_judge_batch(user_model, batch)
            except Exception as exc:
                warnings.append(
                    f"kr3_9: LLM batch failed after {max_attempts} retries: {exc}"
                )
                for i, offer in batch:
                    correct_flags[i] = False
                    issues.append(
                        _make_issue(i, offer, user_model, "llm_error", "llm", str(exc)[:200])
                    )
                continue

            for i, offer in batch:
                if i not in llm_results:
                    correct_flags[i] = False
                    issues.append(_make_issue(i, offer, user_model, "llm_parse_error", "llm"))
                    continue
                matched, reason = llm_results[i]
                correct_flags[i] = matched
                if not matched:
                    issues.append(
                        _make_issue(i, offer, user_model, "llm_rejected", "llm", reason)
                    )

    correct_count = sum(1 for i in range(len(offers)) if correct_flags.get(i, False))
    accuracy = correct_count / len(offers)
    return accuracy, issues, user_model, warnings
