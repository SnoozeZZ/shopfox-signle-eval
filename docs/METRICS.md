# 指标手册

本文档描述评测服务计算的全部指标：**输出 id**、**计算公式**、**是否进入后端回调**、**是否产出 issues**。

实现以源码为准：

- 指标注册：[`SingleProductEval/config.py`](../SingleProductEval/config.py) — `METRICS_REGISTRY`、`CALLBACK_METRIC_IDS`
- 计算逻辑：[`SingleProductEval/metrics.py`](../SingleProductEval/metrics.py)
- 回调组装：[`SingleProductEval/eval_callback_transform.py`](../SingleProductEval/eval_callback_transform.py)

---

## 公共概念

### 过滤后 offer

`priceComparison.offers` 中，`variant_attributes` 与用户 `defaultSelection` 匹配的条目（[`metrics._get_offers`](../SingleProductEval/metrics.py)）。

多数 KR3 准确率指标（链接、SPU、规格、价格、运费、平台服务等）的分母为**过滤后 offer**。

### Top3 / Top5 平台槽位

定义于 `config.py` 中 `TOP3_PLATFORM_SLOTS`、`TOP5_EXTRA_SLOTS`：

- **Top3**：品牌官网 + Amazon +（Walmart 或 Best Buy）
- **Top5**：Top3 + eBay +（Target 或 Lowe's）

### 三套输出

| 输出 | 位置 | 内容 |
|------|------|------|
| `raw_metrics` | `result.json` | 全量：含 `_kr3_*_issues`、canonical 内部别名、`_warnings` |
| `metrics` | `result.json` | `public_metrics`：去掉 `_` 前缀的扁平 dict |
| 回调 `metrics[]` | external-callback | **仅固定 22 个** `CALLBACK_METRIC_IDS`，固定顺序 |

### null 与回调 passed

指标无法计算时（爬虫不可用、无 LLM、无可评测 offer 等）值为 `null`：

- `result.json` 中该键为 `null`
- 回调中对应项：`value=""`，`passed=false`

---

## 表 A：后端回调指标（22 项）

回调 `metrics[].krId` **固定输出下表全部 22 项**，顺序与下表一致。  
`issues[].attributionKr` 的取值必须是下表中的 id（与 `krId` 同一套字符串）。

| 输出 id | 中文名 | KR | valueType | 计算公式 | 依赖 | issues |
|---------|--------|-----|-----------|----------|------|--------|
| `report_success` | 报告是否成功 | KR1 | string | 无 `_eval_error`，存在 `spu_metadata` 与 `priceComparison` → `complete`；否则 `fail` | 报告结构 | 否 |
| `duration_minutes` | 耗时（分钟） | KR2 | number | `searchSummary.totalExecutionTimeSeconds / 60`，保留 2 位小数 | 报告 `searchSummary` | 否 |
| `key_info_valid` | 关键板块有效 | KR3-1 | boolean | spec + 比价区结构校验全部通过（英文、图片 URL、offer 必填字段、url 等） | 规则 + 可选图片 HTTP | **是** |
| `intent_coverage` | 意图覆盖率 | — | percentage | 4 个意图点中「已覆盖」数 / 4 | GT `expected_model_keywords`、`spec_attributes` | 否 |
| `intent_accuracy` | 意图准确率 | — | percentage | 已覆盖意图点中「正确」数 / 已覆盖数 | 同上 | 否 |
| `offer_link_accuracy` | 链接指向准确率 | KR3-8 | percentage | 过滤后 offer 中链接指向商品详情页的比例；静态 URL 规则 + 可选 HTTP 抽检（404、跳转列表页判错） | 规则 + HTTP | **是** |
| `spu_model_accuracy` | SPU 机型准确率 | KR3-9 | percentage | 过滤后 offer 与用户检索机型匹配的比例；规则精确匹配 + 疑难样本 LLM 判定 | `DASHSCOPE_API_KEY`（LLM） | **是** |
| `sku_spec_display_accuracy` | SKU 规格展示准确率 | KR3-10 | percentage | 过滤后 offer 正确展示用户 `defaultSelection` 各维度（含 condition 一致性）的比例 | 规则 | **是** |
| `offer_price_accuracy` | 价格准确率 | KR3-11 | percentage | 可评测 offer 中报告价与爬虫实价一致数 / 可评测数；价差容忍度 `KR3_11_PRICE_TOLERANCE_ABS`（默认 0） | 价格爬虫 `CRAWLER_URL` | **是** |
| `shipping_info_accuracy` | 运费准确率 | KR3-12 | percentage | 过滤后 offer 中 `shippingCost` 非空且非占位符的比例 | 规则 | **是** |
| `rebate_info_accuracy` | 返利/优惠券准确率 | KR3-13 | percentage | 可核验返利条目中与落地页档位一致数 / 尝试核验数；含 cashback 与 coupon | HTTP 抓页 + 规则 + 可选 LLM | **是** |
| `has_user_reviews` | 有用户评论 | KR3-15 | boolean | `reviews` 板块经规范化后有实质内容 | 报告结构 | 否 |
| `has_social_media` | 有社媒反馈 | KR3-16 | boolean | `socialMediaFeedback` 有实质内容 | 报告结构 | 否 |
| `has_expert_reviews` | 有专家评测 | KR3-17 | boolean | `expertReviews` 有实质内容 | 报告结构 | 否 |
| `has_attributes` | 有属性/规格 | KR3-18 | boolean | `specifications` 有实质内容 | 报告结构 | 否 |
| `platform_service_info_accuracy` | 平台服务信息准确率 | KR3-19 | percentage | 过滤后 offer 同时满足：有 `returnPolicy`、有 `shippingTime`、解析出的最大配送天数 ≤ 30 | 规则 | **是** |
| `kr4_3_platform_8_offer` | 3 平台 8 offer | KR4 | boolean | 过滤后去重平台数 ≥ 3 **且** offer 数 ≥ 8 | 规则 | 否 |
| `top3_platform_coverage` | Top3 平台覆盖率 | KR4-1 | percentage | Top3 槽位覆盖数 / 3 | 规则 | 否 |
| `top5_platform_count` | Top5 平台覆盖数 | KR4-2 | integer | Top5 槽位覆盖数（0–5） | 规则 | 否 |
| `top3_link_count` | Top3 链接数 | KR4-3 | integer | 过滤后 offer 中 retailer 属于 Top3 平台集合的条数 | 规则 | 否 |
| `top5_link_count` | Top5 链接数 | KR4-4 | integer | 过滤后 offer 中 retailer 属于 Top5 平台集合的条数 | 规则 | 否 |
| `kr4_5_top3_link_completeness` | Top3 链接完备率 | KR4-5 | percentage | 爬虫参考 Top3 URL（经 SPU 过滤）中出现在报告 Top3 offer 的比例 | 类目扩展爬虫 `CRAWLER_API` + 可选 LLM | **是** |

### 意图 4 点（intent_coverage / intent_accuracy）

| 意图点 | 覆盖条件 | 正确条件 |
|--------|----------|----------|
| `product_model` | 报告有 product_model / product_name | 与 GT `expected_model_keywords` 模糊匹配 |
| `spec_attributes` | defaultSelection 或 variant_schema 出现 GT 规格键 | 各键值与 GT 一致 |
| `search_action` | 存在带 url 的 offer | 有 url 即正确 |
| `comparison_action` | 有 finalRecommendation 或 specifications | 有即正确 |

---

## 表 B：仅内部计算、不进回调的指标

写入 `raw_metrics` / `result.json.metrics`，**不会**出现在 external-callback 的 `metrics[]` 中。

| 输出 id | 中文名 | valueType | 计算公式 |
|---------|--------|-----------|----------|
| `spec_id_completeness` | 规格识别完整度 | percentage | GT `spec_attributes` 各键在 defaultSelection / variant_schema 中被识别数 / 总键数 |
| `spec_id_accuracy` | 规格识别准确度 | percentage | 已识别键中值与 GT 一致数 / 已识别数 |
| `spec_display_completeness` | 规格展示完整度 | percentage | 过滤后 offer 中展示全部 GT 规格键的条数 / offer 总数 |
| `total_platform_count` | 平台总数 | integer | 过滤后 offer 去重 retailer 数 |
| `total_product_links` | 商品链接总数 | integer | 过滤后 offer 条数 |

---

## 表 C：canonical 内部别名

`compute_all_metrics` 可能同时写入对外 id 与内部 canonical 键（同值）。  
回调只输出**对外 id**；若 `raw_metrics` 仅有 canonical 键，通过 `CALLBACK_METRIC_VALUE_FALLBACK` 取值。

| 对外 id（回调 krId） | 内部 canonical 键 |
|---------------------|-------------------|
| `top3_platform_coverage` | `kr4_1_top3_platform_coverage` |
| `top5_platform_count` | `kr4_2_top5_platform_count` |
| `top3_link_count` | `kr4_3_top3_link_count` |
| `top5_link_count` | `kr4_4_top5_link_count` |
| `has_user_reviews` | `kr3_15_user_reviews` |
| `has_social_media` | `kr3_16_social_media` |
| `has_expert_reviews` | `kr3_17_expert_reviews` |
| `has_attributes` | `kr3_18_attributes` |

---

## issues 回调说明

### 字段格式

每条 issue 固定 5 个字段：

| 字段 | 说明 |
|------|------|
| `attributionKr` | 归因指标 id，必为表 A 中带 issues=是 的 id |
| `description` | 英文自然语言描述（≤500 字） |
| `priority` | `P0` / `P1` |
| `section` | 报告板块，如 `priceComparison`、`spec` |
| `link` | 相关 URL，无则 `""` |

### 内部源 → attributionKr

| raw_metrics 键 | attributionKr |
|----------------|---------------|
| `_kr3_1_issues` | `key_info_valid` |
| `_kr3_8_issues` | `offer_link_accuracy` |
| `_kr3_9_issues` | `spu_model_accuracy` |
| `_kr3_10_issues` | `sku_spec_display_accuracy` |
| `_kr3_11_issues` | `offer_price_accuracy` |
| `_kr3_12_issues` | `shipping_info_accuracy` |
| `_kr3_13_issues` | `rebate_info_accuracy` |
| `_kr3_19_issues` | `platform_service_info_accuracy` |
| `_kr4_5_issues` | `kr4_5_top3_link_completeness` |

### 不会进入 issues 的内容

- `raw_metrics._error`、`_warnings`
- `report_success == fail` 的汇总条
- 不可核验 reason：`http_inconclusive`、`no_page_text`、`llm_error` 等（见 `CALLBACK_ISSUE_EXCLUDE_REASONS`）

### 示例

```json
{
  "metrics": [
    { "krId": "offer_price_accuracy", "value": "0.75", "valueType": "percentage", "passed": true, "reason": "" },
    { "krId": "offer_link_accuracy", "value": "0.9", "valueType": "percentage", "passed": true, "reason": "" }
  ],
  "issues": [
    {
      "attributionKr": "offer_price_accuracy",
      "description": "Card shows $499, landing page $549 (Galaxy S25 Ultra · Amazon)",
      "priority": "P0",
      "section": "priceComparison",
      "link": "https://www.amazon.com/dp/..."
    },
    {
      "attributionKr": "offer_link_accuracy",
      "description": "Walmart link invalid (HTTP 404)",
      "priority": "P0",
      "section": "priceComparison",
      "link": "https://www.walmart.com/ip/..."
    }
  ]
}
```

---

## 源码索引

| 输出 id | 计算入口 | 校验/辅助模块 |
|---------|----------|---------------|
| `report_success` | `compute_report_success` | — |
| `duration_minutes` | `compute_duration_minutes` | — |
| `key_info_valid` | `compute_key_info_valid` | `kr3_validators.validate_key_info` |
| `intent_coverage` / `intent_accuracy` | `compute_intent_*` | `_check_intent_points` |
| `offer_link_accuracy` | `compute_offer_link_accuracy` | `kr3_8_link_validator` |
| `spu_model_accuracy` | `compute_spu_model_accuracy` | `kr3_9_spu_validator` |
| `sku_spec_display_accuracy` | `compute_sku_spec_display_accuracy` | `kr3_10_sku_spec_validator` |
| `offer_price_accuracy` | `compute_offer_price_accuracy` | `kr3_11_price_validator` |
| `shipping_info_accuracy` | `compute_shipping_info_accuracy` | `kr3_12_shipping_validator` |
| `rebate_info_accuracy` | `compute_rebate_info_accuracy` | `kr3_13_rebate_validator` |
| `has_user_reviews` | `compute_has_user_reviews` | `_build_kr3_content_stats("reviews")` |
| `has_social_media` | `compute_has_social_media` | `_build_kr3_content_stats("socialMediaFeedback")` |
| `has_expert_reviews` | `compute_has_expert_reviews` | `_build_kr3_content_stats("expertReviews")` |
| `has_attributes` | `compute_has_attributes` | `_build_kr3_content_stats("specifications")` |
| `platform_service_info_accuracy` | `compute_platform_service_info_accuracy` | `kr3_19_platform_service_validator` |
| `kr4_3_platform_8_offer` | `compute_kr4_3_platform_8_offer` | `kr4_platform_offer_validator` |
| `top3_platform_coverage` | `compute_top3_platform_coverage` | `_build_kr4_1_top3_stats` |
| `top5_platform_count` | `compute_top5_platform_count` | `_build_kr4_2_top5_stats` |
| `top3_link_count` | `compute_top3_link_count` | `_build_kr4_3_top3_link_stats` |
| `top5_link_count` | `compute_top5_link_count` | `_build_kr4_4_top5_link_stats` |
| `kr4_5_top3_link_completeness` | `compute_kr4_5_top3_link_completeness` | `kr4_5_link_completeness_validator` |
| `spec_id_completeness` | `compute_spec_identification_completeness` | — |
| `spec_id_accuracy` | `compute_spec_identification_accuracy` | — |
| `spec_display_completeness` | `compute_spec_display_completeness` | — |
| `total_platform_count` | `compute_total_platform_count` | `_platform_analysis` |
| `total_product_links` | `compute_total_product_links` | `_get_offers` |

回调转换：[`eval_callback_transform.build_external_callback_payload`](../SingleProductEval/eval_callback_transform.py)
