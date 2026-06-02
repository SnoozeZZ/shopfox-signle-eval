"""
KR3-13 LLM semantic judge for rebate/cashback claims vs landing page context.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import (
    KR3_13_LLM_BATCH_SIZE,
    KR3_13_LLM_MAX_CLAIM_DESC_CHARS,
    KR3_13_LLM_MAX_EXCLUDED_CHARS,
    KR3_13_LLM_MAX_PAGE_CHARS,
    KR3_13_LLM_MODEL,
    KR3_13_MIN_PAGE_TEXT_LEN,
)
from .llm_client import chat_json

_LLM_SYSTEM_PROMPT = """You are a rebate/cashback accuracy evaluator for e-commerce reports.
Given a cashback portal landing page excerpt (page_context) and one or more report claims,
decide whether each claim accurately reflects the corresponding tier on that page for the stated retailer and category/condition.

Rules:
- Match by the SPECIFIC category/condition tier, not merely any percentage appearing on the page.
- Consider rate, category name, exclusions, and "up to" wording together with page_context and excluded_items.
- If page_context does not contain enough information to locate that category's tier, set verifiable to false.
- Do not mark correct when only a generic store rate matches but the claimed category tier differs.

Respond with ONLY a JSON array, no markdown:
[{"index": 0, "match": true, "verifiable": true, "reason": "brief"}, ...]
"""

_PCT_HINT_RE = re.compile(r"%|\d+\s*%\s*cash", re.I)
_KEYWORD_RE = re.compile(
    r"cash\s*back|cashback|coupon|exclusion|eligible|category|tier|rate",
    re.I,
)
_LINE_SPLIT_RE = re.compile(r"[\n\r]+|(?<=[.!?])\s+")


def build_claim_payload(
    index: int,
    item: dict,
    claim: dict[str, Any],
) -> dict[str, Any]:
    desc = str(claim.get("description") or "")
    if len(desc) > KR3_13_LLM_MAX_CLAIM_DESC_CHARS:
        desc = desc[: KR3_13_LLM_MAX_CLAIM_DESC_CHARS] + "…"
    excluded = str(claim.get("excluded_items") or "")
    if len(excluded) > KR3_13_LLM_MAX_EXCLUDED_CHARS:
        excluded = excluded[: KR3_13_LLM_MAX_EXCLUDED_CHARS] + "…"
    return {
        "index": index,
        "retailer": str(item.get("retailer") or ""),
        "source": str(item.get("source") or ""),
        "type": str(item.get("type") or "cashback"),
        "category": claim.get("category") or "",
        "rate_pct": claim.get("rate_pct"),
        "amount": item.get("amount"),
        "description": desc,
        "excluded_items": excluded,
        "up_to": bool(claim.get("up_to")),
    }


def compress_page_for_llm(
    page_text: str,
    hint_categories: list[str] | None = None,
) -> str:
    """Keep lines likely containing tier tables; cap total length."""
    if not page_text:
        return ""

    hints = [h for h in (hint_categories or []) if h]
    hint_lower = {h.lower() for h in hints}

    def _line_score(line: str) -> int:
        lower = line.lower()
        score = 0
        if _PCT_HINT_RE.search(line):
            score += 3
        if any(h in lower for h in hint_lower):
            score += 4
        if _KEYWORD_RE.search(line):
            score += 2
        if len(line) > 40:
            score += 1
        return score

    chunks: list[str] = []
    for part in _LINE_SPLIT_RE.split(page_text):
        line = part.strip()
        if len(line) < 12:
            continue
        if _line_score(line) > 0:
            chunks.append(line)

    if not chunks:
        chunks = [page_text[: KR3_13_LLM_MAX_PAGE_CHARS]]

    seen: set[str] = set()
    ordered: list[str] = []
    for c in chunks:
        key = c[:120]
        if key in seen:
            continue
        seen.add(key)
        ordered.append(c)

    out = "\n".join(ordered)
    if len(out) > KR3_13_LLM_MAX_PAGE_CHARS:
        out = out[: KR3_13_LLM_MAX_PAGE_CHARS]
    return out


def page_context_sufficient(compressed: str) -> bool:
    return len(compressed or "") >= KR3_13_MIN_PAGE_TEXT_LEN


def _parse_llm_results(raw: Any) -> dict[int, dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("results") or raw.get("claims") or [raw]
    if not isinstance(raw, list):
        raise ValueError("LLM response is not a JSON array")

    parsed: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if idx is None:
            continue
        parsed[int(idx)] = {
            "match": bool(item.get("match")),
            "verifiable": bool(item.get("verifiable", True)),
            "reason": str(item.get("reason") or "")[:300],
        }
    return parsed


def llm_judge_url_batch(
    url: str,
    page_context: str,
    retailer: str,
    source: str,
    claims: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Judge a batch of claims sharing the same URL and page_context."""
    payload = {
        "url": url[:500],
        "retailer": retailer,
        "source": source,
        "page_context": page_context,
        "claims": claims,
    }
    user_msg = json.dumps(payload, ensure_ascii=False)
    raw = chat_json(_LLM_SYSTEM_PROMPT, user_msg, model=KR3_13_LLM_MODEL, enable_thinking=False)
    return _parse_llm_results(raw)


def chunk_claims(
    claim_payloads: list[dict[str, Any]],
    batch_size: int | None = None,
) -> list[list[dict[str, Any]]]:
    size = batch_size or KR3_13_LLM_BATCH_SIZE
    return [claim_payloads[i : i + size] for i in range(0, len(claim_payloads), size)]
