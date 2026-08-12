"""
KR3-9 validators: SPU model scope accuracy (user model vs offer model + title).

Rule layer: norm(product_model) == norm(user_model) only when model is semantic.
Non-semantic models (barcodes, UPCs, ASINs, placeholder values) are ignored for
comparison; LLM judges from product_name. Broad user queries allow same-line variants.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from .config import KR3_9_LLM_BATCH_SIZE, KR3_9_LLM_MAX_RETRIES, KR3_9_LLM_MODEL, KR3_9_USE_LLM
from .llm_client import chat_json, has_dashscope_api_key

OfferRoute = Literal["exact_match", "empty_mismatch", "needs_llm"]

_INVALID_MODEL_VALUES = frozenset({"", "n/a", "na", "none", "null", "unknown"})

# "Item model number : 00038100168610" / "model number: 12345"
_MODEL_NUMBER_PREFIX_RE = re.compile(
    r"^(?:item\s+)?model\s*number\s*:?\s*",
    re.IGNORECASE,
)
# Amazon ASIN: B0 + 8 alphanumeric
_ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$", re.IGNORECASE)

_LLM_SYSTEM_PROMPT = """You are a product model matching evaluator for e-commerce offers.
Given a user's target product model and a list of offers (each with product_model and product_name/title),
decide whether each offer refers to the SAME product line / SPU intent as the user requested.

Rules:
- If product_model is empty, treat it as unavailable and judge ONLY from product_name.
- When product_model is present and looks like a real model name, consider it together with product_name.
- Broad user queries (series / main formula only, e.g. "Pro Plan Chicken & Rice", without size class,
  wet/dry, or life-stage): MATCH if the offer is the same brand/line and the title reflects the same
  main formula keywords. Do NOT reject solely because of Small/Large Breed, Wet/Dry/Pate/Canned,
  Puppy/Adult/Senior, bag weight, or pack size when the user did not specify those constraints.
- When the user explicitly requests a variant constraint (e.g. "Small Breed", "Wet", "Puppy",
  "Q3 43", "iPhone Air Mini"), require that constraint to match.
- Specific sub-model mismatches still fail when the user named a precise model
  (e.g. user wants "Leica Q3" but offer is "Q3 43" / "Q3 Monochrome"; "iPhone Air" vs "iPhone Air Mini").
- Accessories, bundles for other products, clearly different brands/lines, or unrelated products
  are NOT a match.

Respond with ONLY a JSON array, no markdown:
[{"index": 0, "match": true, "reason": "brief explanation"}, ...]
"""


def derive_user_model(report: dict, gt: dict) -> str:
    val = gt.get("user_model")
    if val and str(val).strip():
        return str(val).strip()

    spu = report.get("spu_metadata") or {}
    for src in (
        spu.get("product_model"),
        spu.get("product_name"),
        report.get("query"),
        spu.get("original_query"),
        report.get("name"),
    ):
        if src and str(src).strip():
            return str(src).strip()

    if not gt.get("_report_first_gt"):
        st = gt.get("search_term")
        if st and str(st).strip():
            return str(st).strip()

    return ""


def _norm(text: str) -> str:
    return re.sub(r"[\s\-_.]+", "", str(text or "").lower())


def _alnum_only(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(text or ""))


def _is_non_semantic_model(text: str) -> bool:
    """
    True when product_model is empty/placeholder, barcode/UPC/SKU digits,
    'Item model number : …', or Amazon ASIN — not usable for exact match.
    """
    raw = str(text or "").strip()
    if not raw:
        return True
    if raw.lower() in _INVALID_MODEL_VALUES:
        return True

    stripped = _MODEL_NUMBER_PREFIX_RE.sub("", raw).strip()
    candidate = stripped if stripped else raw
    alnum = _alnum_only(candidate)

    if not alnum:
        return True
    if _ASIN_RE.match(alnum):
        return True
    # Pure digit catalog/UPC/internal SKU (len >= 5)
    if alnum.isdigit() and len(alnum) >= 5:
        return True
    return False


def _is_invalid_model(text: str) -> bool:
    """Backward-compat alias: non-semantic models count as invalid for comparison."""
    return _is_non_semantic_model(text)


def _is_exact_model_match(product_model: str, user_model: str) -> bool:
    if _is_non_semantic_model(product_model):
        return False
    pm, um = _norm(product_model), _norm(user_model)
    return bool(pm and um and pm == um)


def _is_empty_offer(product_model: str, product_name: str) -> bool:
    return _is_non_semantic_model(product_model) and not str(product_name or "").strip()


def _semantic_product_model_for_llm(product_model: str) -> str:
    """Return model string for LLM payload; blank when non-semantic."""
    raw = str(product_model or "").strip()
    if _is_non_semantic_model(raw):
        return ""
    return raw


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
                "product_model": _semantic_product_model_for_llm(
                    str(offer.get("product_model") or "")
                ),
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
