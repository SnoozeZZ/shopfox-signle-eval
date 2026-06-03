"""
Configuration constants for the SingleProduct evaluation pipeline.
"""

from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent

# ═══════════════════════════════════════════════════════════════════════════════
# KR3-1 validation options
# ═══════════════════════════════════════════════════════════════════════════════

KR3_1_VALIDATE_IMAGE_HTTP = True
KR3_1_IMAGE_HTTP_TIMEOUT_SEC = 5.0

# ═══════════════════════════════════════════════════════════════════════════════
# KR3-8 validation options
# ═══════════════════════════════════════════════════════════════════════════════

KR3_8_VALIDATE_HTTP = True
KR3_8_HTTP_TIMEOUT_SEC = 5.0

# ═══════════════════════════════════════════════════════════════════════════════
# KR3-9 validation options
# ═══════════════════════════════════════════════════════════════════════════════

KR3_9_USE_LLM = True
KR3_9_LLM_MODEL = "qwen3.6-plus"
KR3_9_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
KR3_9_LLM_BATCH_SIZE = 20
KR3_9_LLM_TIMEOUT_SEC = 30
KR3_9_LLM_MAX_RETRIES = 3
KR3_9_LLM_RETRY_BACKOFF_SEC = 2.0

# ═══════════════════════════════════════════════════════════════════════════════
# KR3-11 validation options
# ═══════════════════════════════════════════════════════════════════════════════

KR3_11_USE_CRAWLER = True
KR3_11_PRICE_TOLERANCE_ABS = 0.0

# Crawler defaults (override via .env: CRAWLER_URL, CRAWLER_REQUEST_TIMEOUT, etc.)
CRAWLER_URL_DEFAULT = "http://47.251.122.154:8762/api/ai/crawl/price"
CRAWLER_REQUEST_TIMEOUT_DEFAULT = 60.0
CRAWLER_BATCH_SIZE_DEFAULT = 31
CRAWLER_MAX_IN_FLIGHT_DEFAULT = 32
CRAWLER_SUBMIT_INTERVAL_DEFAULT = 1.0
CRAWLER_MAX_RETRIES_DEFAULT = 3
CRAWLER_RETRY_BACKOFF_SEC_DEFAULT = 2.0

# ═══════════════════════════════════════════════════════════════════════════════
# KR3-19 validation options
# ═══════════════════════════════════════════════════════════════════════════════

KR3_19_MAX_DELIVERY_DAYS = 30

# ═══════════════════════════════════════════════════════════════════════════════
# KR3-13 validation options
# ═══════════════════════════════════════════════════════════════════════════════

KR3_13_VALIDATE_HTTP = True
KR3_13_HTTP_TIMEOUT_SEC = 8.0
KR3_13_HTTP_MAX_WORKERS = 5
KR3_13_MIN_PAGE_TEXT_LEN = 200
KR3_13_RATE_TOLERANCE_PCT = 0.5
KR3_13_DESC_MIN_TOKEN_OVERLAP = 3
KR3_13_SUPPORTED_TYPES = frozenset({"cashback", "coupon"})
KR3_13_SUPPORTED_SOURCES = frozenset({
    "rakuten",
    "befrugal",
    "topcashback",
    "rebatesme",
    "shopathome",
    "mr rebates",
    "swagbucks",
    "upside",
})

KR3_13_USE_LLM = True
KR3_13_LLM_MODEL = KR3_9_LLM_MODEL
KR3_13_LLM_BATCH_SIZE = 12
KR3_13_LLM_MAX_PAGE_CHARS = 12_000
KR3_13_LLM_MAX_CLAIM_DESC_CHARS = 600
KR3_13_LLM_MAX_EXCLUDED_CHARS = 800

# ═══════════════════════════════════════════════════════════════════════════════
# Quality thresholds (used by KR4 platform metrics)
# ═══════════════════════════════════════════════════════════════════════════════

PROMPT_MIN_PLATFORMS = 5
PROMPT_MIN_PRODUCT_LINKS = 20

KR4_MIN_PLATFORMS = 3
KR4_MIN_OFFERS = 8

# ═══════════════════════════════════════════════════════════════════════════════
# KR4-5 validation options (category expand crawler)
# ═══════════════════════════════════════════════════════════════════════════════

KR4_5_CRAWLER_API_DEFAULT = "http://47.77.190.33:8763/api/category/expand"
KR4_5_CRAWLER_TIMEOUT_SEC_DEFAULT = 600.0
KR4_5_CRAWLER_PLATFORMS = ("amazon", "bestbuy", "Walmart")
KR4_5_CRAWLER_MAX_RETRIES = 2
KR4_5_CRAWLER_RETRY_BACKOFF_SEC = 2.0
KR4_5_USE_CRAWLER_CACHE = True
KR4_5_CACHE_DIR = _PKG_DIR / "eval_logs" / "crawler_cache"
KR4_5_USE_FIXTURE_FALLBACK = True
KR4_5_ISSUES_MAX = 50
KR4_5_ECOMMERCE_RETAILERS = frozenset({"Amazon", "Walmart", "Best Buy"})

# ═══════════════════════════════════════════════════════════════════════════════
# Platform tier definitions
# Top 3: Brand Official + Amazon + (Walmart OR BestBuy)
# Top 5: Top 3 + eBay + (Target OR Lowe's)
# ═══════════════════════════════════════════════════════════════════════════════

TOP3_PLATFORM_SLOTS = [
    {"slot": "brand_official", "match": "brand_official"},
    {"slot": "amazon", "match": ["Amazon"]},
    {"slot": "walmart_or_bestbuy", "match": ["Walmart", "Best Buy", "BestBuy"]},
]

TOP5_EXTRA_SLOTS = [
    {"slot": "ebay", "match": ["eBay"]},
    {"slot": "target_or_lowes", "match": ["Target", "Lowe's", "Lowes"]},
]

# ═══════════════════════════════════════════════════════════════════════════════
# Canonical retailer name mapping (normalize variants → canonical)
# ═══════════════════════════════════════════════════════════════════════════════

RETAILER_ALIASES = {
    "amazon": "Amazon",
    "amazon.com": "Amazon",
    "ebay": "eBay",
    "ebay.com": "eBay",
    "walmart": "Walmart",
    "walmart.com": "Walmart",
    "best buy": "Best Buy",
    "bestbuy": "Best Buy",
    "bestbuy.com": "Best Buy",
    "target": "Target",
    "target.com": "Target",
    "lowe's": "Lowe's",
    "lowes": "Lowe's",
    "lowes.com": "Lowe's",
    "newegg": "Newegg",
    "newegg.com": "Newegg",
    "costco": "Costco",
    "costco.com": "Costco",
    "home depot": "Home Depot",
    "homedepot.com": "Home Depot",
    "b&h photo": "B&H Photo",
    "bhphotovideo.com": "B&H Photo",
    "gamestop": "GameStop",
    "gamestop.com": "GameStop",
}

# ═══════════════════════════════════════════════════════════════════════════════
# External callback — metric id as krId (skip registry alias ids)
# ═══════════════════════════════════════════════════════════════════════════════

CALLBACK_SKIP_METRIC_IDS = frozenset({
    "top3_platform_coverage",
    "top5_platform_count",
    "top3_link_count",
    "top5_link_count",
    "has_user_reviews",
    "has_social_media",
    "has_expert_reviews",
    "has_attributes",
})

CALLBACK_ISSUE_SOURCE_MAP: dict[str, str] = {
    "_kr3_1_issues": "key_info_valid",
    "_kr3_8_issues": "offer_link_accuracy",
    "_kr3_9_issues": "spu_model_accuracy",
    "_kr3_10_issues": "sku_spec_display_accuracy",
    "_kr3_11_issues": "offer_price_accuracy",
    "_kr3_12_issues": "shipping_info_accuracy",
    "_kr3_13_issues": "rebate_info_accuracy",
    "_kr3_19_issues": "platform_service_info_accuracy",
    "_kr4_5_issues": "kr4_5_top3_link_completeness",
}

CALLBACK_ISSUES_MAX = 200

# ═══════════════════════════════════════════════════════════════════════════════
# Metrics registry — each metric can be toggled on/off in the rubric
# ═══════════════════════════════════════════════════════════════════════════════

METRICS_REGISTRY = [
    {
        "id": "report_success",
        "name": "Report Success",
        "group": "Run Metrics",
        "description": "Whether the report completed successfully (complete/fail)",
        "type": "string",
        "enabled": True,
    },
    {
        "id": "duration_minutes",
        "name": "Duration (minutes)",
        "group": "Run Metrics",
        "description": "Agent execution time in minutes from searchSummary",
        "type": "number",
        "enabled": True,
    },
    {
        "id": "key_info_valid",
        "name": "Key Info Valid",
        "group": "Key Info",
        "description": "Spec + price-comparison sections structurally correct (KR3-1)",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "offer_link_accuracy",
        "name": "Offer Link Accuracy",
        "group": "Key Info",
        "description": "KR3-8: % of filtered offers linking to product detail pages",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "spu_model_accuracy",
        "name": "SPU Model Accuracy",
        "group": "Key Info",
        "description": "KR3-9: % of filtered offers whose model+title match user input SPU",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "sku_spec_display_accuracy",
        "name": "SKU Spec Display Accuracy",
        "group": "Key Info",
        "description": "KR3-10: % of filtered offers displaying user-selected specs correctly (VA + condition)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "offer_price_accuracy",
        "name": "Offer Price Accuracy",
        "group": "Key Info",
        "description": "KR3-11: % of evaluable offers whose recorded price matches crawled live price",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "shipping_info_accuracy",
        "name": "Shipping Cost Accuracy",
        "group": "Key Info",
        "description": "KR3-12: % of filtered offers with shipping cost present (rule only)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "platform_service_info_accuracy",
        "name": "Platform Service Info Accuracy",
        "group": "Key Info",
        "description": "KR3-19: Return present; delivery present and <=30 days (rule only)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "rebate_info_accuracy",
        "name": "KR3-13 Rebate Info Accuracy",
        "group": "Info Checks",
        "description": "KR3-13: rebate/cashback claims match landing page tier (rate, category, text, link)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "intent_coverage",
        "name": "Intent Coverage",
        "group": "Intent Recognition",
        "description": "% of intent points covered (model, specs, search, comparison — 4 points)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "intent_accuracy",
        "name": "Intent Accuracy",
        "group": "Intent Recognition",
        "description": "% of covered intent points that are correct (4 points)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "spec_id_completeness",
        "name": "Spec ID Completeness",
        "group": "Spec Recognition",
        "description": "% of required spec attributes identified by agent",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "spec_id_accuracy",
        "name": "Spec ID Accuracy",
        "group": "Spec Recognition",
        "description": "% of identified spec attributes with correct values",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "spec_display_completeness",
        "name": "Spec Display Completeness",
        "group": "Spec Display",
        "description": "% of offers with all required spec attributes displayed",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "kr4_3_platform_8_offer",
        "name": "KR4 3 Platform 8 Offer",
        "group": "Platform Coverage",
        "description": "KR4: filtered offers meet >=3 platforms and >=8 offers",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "kr4_1_top3_platform_coverage",
        "name": "KR4-1 Top 3 Platform Coverage",
        "group": "Platform Coverage",
        "description": "KR4-1: brand official + Amazon + Walmart/BestBuy slot coverage (covered/3)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "top3_platform_coverage",
        "name": "Top 3 Platform Coverage",
        "group": "Platform Coverage",
        "description": "Alias of kr4_1_top3_platform_coverage (backward compat)",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "kr4_2_top5_platform_count",
        "name": "KR4-2 Top 5 Platform Count",
        "group": "Platform Coverage",
        "description": "KR4-2: top5 slot coverage count (top3 + eBay + Target/Lowe's, 0-5)",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "top5_platform_count",
        "name": "Top 5 Platform Count",
        "group": "Platform Coverage",
        "description": "Alias of kr4_2_top5_platform_count (backward compat)",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "total_platform_count",
        "name": "Total Platform Count",
        "group": "Platform Coverage",
        "description": "Total distinct platforms in results",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "total_product_links",
        "name": "Total Product Links",
        "group": "Platform Coverage",
        "description": "Total offer count (matching default SKU)",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "kr4_3_top3_link_count",
        "name": "KR4-3 Top 3 Link Count",
        "group": "Platform Coverage",
        "description": "KR4-3: filtered offers whose retailer is in top3 platform set",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "top3_link_count",
        "name": "Top 3 Link Count",
        "group": "Platform Coverage",
        "description": "Alias of kr4_3_top3_link_count (backward compat)",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "kr4_4_top5_link_count",
        "name": "KR4-4 Top 5 Link Count",
        "group": "Platform Coverage",
        "description": "KR4-4: filtered offers whose retailer is in top5 platform set",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "top5_link_count",
        "name": "Top 5 Link Count",
        "group": "Platform Coverage",
        "description": "Alias of kr4_4_top5_link_count (backward compat)",
        "type": "integer",
        "enabled": True,
    },
    {
        "id": "kr4_5_top3_link_completeness",
        "name": "KR4-5 Top3 Link Completeness",
        "group": "Platform Coverage",
        "description": "KR4-5: share of crawler-valid top3 URLs present in report top3 offers",
        "type": "percentage",
        "enabled": True,
    },
    {
        "id": "kr3_15_user_reviews",
        "name": "KR3-15 User Reviews",
        "group": "Info Checks",
        "description": "KR3-15: report includes user review section content",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "has_user_reviews",
        "name": "Has User Reviews",
        "group": "Info Checks",
        "description": "Alias of kr3_15_user_reviews (backward compat)",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "kr3_16_social_media",
        "name": "KR3-16 Social Media",
        "group": "Info Checks",
        "description": "KR3-16: report includes social media feedback section content",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "has_social_media",
        "name": "Has Social Media",
        "group": "Info Checks",
        "description": "Alias of kr3_16_social_media (backward compat)",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "kr3_17_expert_reviews",
        "name": "KR3-17 Expert Reviews",
        "group": "Info Checks",
        "description": "KR3-17: report includes expert review section content",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "has_expert_reviews",
        "name": "Has Expert Reviews",
        "group": "Info Checks",
        "description": "Alias of kr3_17_expert_reviews (backward compat)",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "kr3_18_attributes",
        "name": "KR3-18 Attributes",
        "group": "Info Checks",
        "description": "KR3-18: report includes product specifications/attributes content",
        "type": "boolean",
        "enabled": True,
    },
    {
        "id": "has_attributes",
        "name": "Has Attributes",
        "group": "Info Checks",
        "description": "Alias of kr3_18_attributes (backward compat)",
        "type": "boolean",
        "enabled": True,
    },
]

DEFAULT_ENABLED_METRICS = [m["id"] for m in METRICS_REGISTRY]

# ═══════════════════════════════════════════════════════════════════════════════
# Default rubric — metrics + parameters
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_RUBRIC = {
    "enabled_metrics": DEFAULT_ENABLED_METRICS,
    "min_platforms": PROMPT_MIN_PLATFORMS,
    "min_product_links": PROMPT_MIN_PRODUCT_LINKS,
    "top3_slots": TOP3_PLATFORM_SLOTS,
    "top5_extra_slots": TOP5_EXTRA_SLOTS,
    "retailer_aliases": RETAILER_ALIASES,
}

# ═══════════════════════════════════════════════════════════════════════════════
# Runner defaults
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_API_BASE_URL = "http://localhost:8000"
DEFAULT_CONCURRENCY = 3
DEFAULT_POLL_INTERVAL_SEC = 10.0
DEFAULT_TIMEOUT_SEC = 900  # 15 minutes per product
