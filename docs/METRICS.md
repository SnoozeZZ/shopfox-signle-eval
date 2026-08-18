# 指标手册

本文档描述评测服务计算的全部指标：**输出 id**、**计算公式**、**是否进入后端回调**、**是否产出 issues**。

若要按指标理解「代表什么、怎么算」，请先看 **[指标说明.md](./指标说明.md)**。

实现以源码为准：

- 指标注册：[`SingleProductEval/config.py`](../SingleProductEval/config.py) — `METRICS_REGISTRY`、`CALLBACK_METRIC_IDS`
- 计算逻辑：[`SingleProductEval/metrics.py`](../SingleProductEval/metrics.py)
- 回调组装：[`SingleProductEval/eval_callback_transform.py`](../SingleProductEval/eval_callback_transform.py)

---

## 公共概念

### 全量 offer

所有与 offer 相关的指标分母均为 `priceComparison.offers` **全部条目**（[`metrics._get_offers`](../SingleProductEval/metrics.py) = `_get_all_offers`）。

`defaultSelection` **不参与** offer 集合筛选，也不作为 KR3-10 的正确性对照。UI 切换规格仅影响前端展示子集；评测侧 treats 数组内每条 offer 为有效条目。

**KR3-10 特例**：每条 offer 检查 `variant_attributes` 存在且各维度值非空（不校验顶层 `condition` 与 `variant_attributes.Condition` 是否一致）。

### Top3 / Top5 平台槽位

定义于 `config.py` 中 `TOP3_ECOMMERCE_SLOTS`、`TOP5_PLATFORM_SLOTS`：

- **Top3 电商槽**（各算 1）：Amazon、Walmart、Best Buy
- **KR4-1 覆盖率**：`min(1, (电商槽覆盖数 + 官网加分) / 3)`；官网为可选加分（URL 命中 GT `brand_official_domains`），非必填
- **Top5 电商槽**（0–5 整数，**不含官网**）：Top3 电商三平台 + eBay +（Target 或 Lowe's）
- **链接数**（KR4-3 / KR4-4）：全量 offer **条数**；官网 offer 以 URL 命中 `brand_official_domains` 识别为 `Brand Official`，不论 `retailer` 字段是否为品牌名

### 三套输出

| 输出 | 位置 | 内容 |
|------|------|------|
| `raw_metrics` | `result.json` | 全量：含 `_kr3_*_issues`、canonical 内部别名、`_warnings` |
| `metrics` | `result.json` | `public_metrics`：去掉 `_` 前缀的扁平 dict |
| 回调 `metrics[]` | external-callback | **仅固定 36 个** `CALLBACK_METRIC_IDS`，固定顺序（KR3-11 已暂时移出；含 KR4-6/7/8/9） |

### null 与回调 passed

指标无法计算时（爬虫不可用、无 LLM、无可评测 offer 等）值为 `null`：

- `result.json` 中该键为 `null`
- 回调中对应项：`value=""`，`passed=false`

---

## 表 A：后端回调指标（36 项）

回调 `metrics[].krId` **固定输出下表全部 36 项**，顺序与下表一致。  
`issues[].attributionKr` 的取值必须是下表中带 issues=是 的 id（与 `krId` 同一套字符串）；综合分相关 id（`eval_dim_*`、`eval_final_score`）不产生 issues。

后缀约定：`*_score` = 档位分（0–100）；`*_contrib` = 贡献分（档位分 × 0.2）。

| 输出 id | 中文名 | KR | valueType | 计算公式 | 依赖 | issues |
|---------|--------|-----|-----------|----------|------|--------|
| `report_success` | 报告是否成功 | KR1 | string | 无 `_eval_error`，存在 `spu_metadata` 与 `priceComparison` → `complete`；否则 `fail` | 报告结构 | 否 |
| `duration_minutes` | 耗时（分钟） | KR2 | number | `searchSummary.totalExecutionTimeSeconds / 60`，保留 2 位小数 | 报告 `searchSummary` | 否 |
| `key_info_valid` | 关键板块有效 | KR3-1 | boolean | spec + 比价区结构校验全部通过（英文、图片 URL、offer 必填字段、url 等） | 规则 + 可选图片 HTTP | **是** |
| `intent_coverage` | 意图覆盖率 | — | percentage | 4 个意图点中「已覆盖」数 / 4 | GT `expected_model_keywords`、`spec_attributes` | 否 |
| `intent_accuracy` | 意图准确率 | — | percentage | 已覆盖意图点中「正确」数 / 已覆盖数 | 同上 | 否 |
| `offer_link_accuracy` | 链接指向准确率 | KR3-8 | percentage | 全量 offer 中链接指向商品详情页的比例；静态 URL 规则 + 可选 HTTP 抽检（404、跳转列表页判错） | 规则 + HTTP | **是** |
| `spu_model_accuracy` | SPU 机型准确率 | KR3-9 | percentage | 全量 offer（排除 `is_target_product=false`）与用户检索机型匹配的比例；规则 + LLM。条码/货号/ASIN 等非语义 `product_model` 不参与比对，以 `product_name` 为主；泛检索下同系列主配方变体放宽（体型/干湿/生命阶段未指定则不单凭此拒判） | `DASHSCOPE_API_KEY`（LLM） | **是** |
| `sku_spec_display_accuracy` | SKU 规格展示准确率 | KR3-10 | percentage | 全量 offer 中 `variant_attributes` 存在且各维度值非空的比例 | 规则 | **是** |
| `offer_price_accuracy` | 价格准确率 | KR3-11 | percentage | **暂时停用**：不计算、不进回调；代码保留便于恢复 | — | 否 |
| `shipping_info_accuracy` | 运费准确率 | KR3-12 | percentage | 全量 offer 中 `shippingCost` 非空且非占位符的比例 | 规则 | **是** |
| `rebate_info_accuracy` | 返利/优惠券准确率 | KR3-13 | percentage | 可核验返利条目中与落地页档位一致数 / 尝试核验数；含 cashback 与 coupon | HTTP 抓页 + 规则 + 可选 LLM | **是** |
| `has_user_reviews` | 有用户评论 | KR3-15 | boolean | `reviews` 板块经规范化后有实质内容 | 报告结构 | 否 |
| `has_social_media` | 有社媒反馈 | KR3-16 | boolean | `socialMediaFeedback` 有实质内容 | 报告结构 | 否 |
| `has_expert_reviews` | 有专家评测 | KR3-17 | boolean | `expertReviews` 有实质内容 | 报告结构 | 否 |
| `has_attributes` | 有属性/规格 | KR3-18 | boolean | `specifications` 有实质内容 | 报告结构 | 否 |
| `platform_service_info_accuracy` | 平台服务信息准确率 | KR3-19 | percentage | 全量 offer 同时满足：有 `returnPolicy`、有 `shippingTime`、解析出的最大配送天数 ≤ 30 | 规则 | **是** |
| `kr4_3_platform_8_offer` | 5 平台 20 offer | KR4 | boolean | 全量 offer 去重平台数 ≥ 5 **且** offer 数 ≥ 20（krId 历史命名保留） | 规则 | 否 |
| `top3_platform_coverage` | Top3 平台覆盖率 | KR4-1 | percentage | `min(1, (Amazon+Walmart+BestBuy 槽覆盖数 + 官网加分) / 3)` | 规则 | 否 |
| `top5_platform_count` | Top5 平台覆盖数 | KR4-2 | integer | Top5 电商槽覆盖数（0–5，不含官网） | 规则 | 否 |
| `top3_link_count` | Top3 链接数 | KR4-3 | integer | 全量 offer 中属于 Top3 平台集合的条数（含官网 URL 识别） | 规则 | 否 |
| `top5_link_count` | Top5 链接数 | KR4-4 | integer | 全量 offer 中属于 Top5 平台集合的条数（含官网 URL 识别） | 规则 | 否 |
| `kr4_5_top3_link_completeness` | Top3 链接完备率 | KR4-5 | percentage | 爬虫参考 Top3 URL（经 SPU 过滤）中出现在报告 Top3 offer 的比例 | 类目扩展爬虫 `CRAWLER_API` + 可选 LLM | **是** |
| `kr4_6_distinct_platform_count` | 去重平台数量 | KR4-6 | integer | 全量 offer 去重 retailer 数（与内部 `total_platform_count` 同逻辑） | 规则 | 否 |
| `kr4_7_unique_offer_count` | SPU 维度 offer 数量 | KR4-7 | integer | 合法 url 按 strip 原串去重（保留 tracking）+ 非法非空 url 每条各计 1；空 url 不计 | 规则 | 否 |
| `kr4_8_sku_avg_platform_count` | SKU 平均平台数 | KR4-8 | number | KR4-6 ÷ SKU 规格组合数；组合数 = `sku_combinations[].variant_attributes` 各规格维度选项去重后的笛卡尔积（含未出现组合；不用 `variant_schema`）；分母为 0 时不输出 | 规则 | 否 |
| `kr4_9_sku_avg_offer_count` | SKU 平均链接数 | KR4-9 | number | KR4-7 ÷ SKU 规格组合数（分母同 KR4-8）；分母为 0 时不输出 | 规则 | 否 |
| `eval_dim_platform_count_score` | 平台数量档位分 | — | number | 去重平台数分层后的档位分（0–100） | `report_composite_score` | 否 |
| `eval_dim_platform_count_contrib` | 平台数量贡献分 | — | number | 平台数量档位分 × 0.2 | `report_composite_score` | 否 |
| `eval_dim_offer_count_score` | Offer 数量档位分 | — | number | 全量 offer 条数分层后的档位分（≥15 → 100） | `report_composite_score` | 否 |
| `eval_dim_offer_count_contrib` | Offer 数量贡献分 | — | number | Offer 数量档位分 × 0.2 | `report_composite_score` | 否 |
| `eval_dim_offer_info_accuracy_score` | Offer 信息准确率档位分 | — | number | 链接准确率分层后的档位分（0–100；价格侧暂时停用） | `report_composite_score` | 否 |
| `eval_dim_offer_info_accuracy_contrib` | Offer 信息准确率贡献分 | — | number | Offer 信息准确率档位分 × 0.2 | `report_composite_score` | 否 |
| `eval_dim_product_info_accuracy_score` | 商品信息准确率档位分 | — | number | 图片结构 + 规格展示；满分仅当规格 100% 且图片通过 | `report_composite_score` | 否 |
| `eval_dim_product_info_accuracy_contrib` | 商品信息准确率贡献分 | — | number | 商品信息准确率档位分 × 0.2 | `report_composite_score` | 否 |
| `eval_dim_section_completeness_score` | 版块完整率档位分 | — | number | 6 版块齐全率分层后的档位分（0–100） | `report_composite_score` | 否 |
| `eval_dim_section_completeness_contrib` | 版块完整率贡献分 | — | number | 版块完整率档位分 × 0.2 | `report_composite_score` | 否 |
| `eval_final_score` | 综合最终分 | — | number | 五维贡献分之和（`composite_score.eval_final_score`），理论最高 100 | `report_composite_score` | 否 |

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
| `spec_display_completeness` | 规格展示完整度 | percentage | 全量 offer 中展示全部 GT 规格键的条数 / offer 总数 |
| `total_platform_count` | 平台总数 | integer | 全量 offer 去重 retailer 数 |
| `total_product_links` | 商品链接总数 | integer | 全量 offer 条数 |

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
    { "krId": "offer_link_accuracy", "value": "0.9", "valueType": "percentage", "passed": true, "reason": "" },
    { "krId": "spu_model_accuracy", "value": "0.85", "valueType": "percentage", "passed": true, "reason": "" }
  ],
  "issues": [
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
| `offer_price_accuracy` | `compute_offer_price_accuracy`（暂时不启用） | `kr3_11_price_validator` |
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
| `kr4_6_distinct_platform_count` | `compute_kr4_6_distinct_platform_count` | `compute_total_platform_count` |
| `kr4_7_unique_offer_count` | `compute_kr4_7_unique_offer_count` | — |
| `kr4_8_sku_avg_platform_count` | `compute_kr4_8_sku_avg_platform_count` | `_sku_spec_combination_count` + KR4-6 |
| `kr4_9_sku_avg_offer_count` | `compute_kr4_9_sku_avg_offer_count` | `_sku_spec_combination_count` + KR4-7 |
| `spec_id_completeness` | `compute_spec_identification_completeness` | — |
| `spec_id_accuracy` | `compute_spec_identification_accuracy` | — |
| `spec_display_completeness` | `compute_spec_display_completeness` | — |
| `total_platform_count` | `compute_total_platform_count` | `_platform_analysis` |
| `total_product_links` | `compute_total_product_links` | `_get_offers` |

回调转换：[`eval_callback_transform.build_external_callback_payload`](../SingleProductEval/eval_callback_transform.py)

---

## 综合分（composite_score）

单份报告在 KR 指标之外额外计算 **5 个 SKU 维度**综合分，写入 `result.json` 的 `composite_score` 字段；五维档位分 / 贡献分与最终分一并注入 `raw_metrics` / `metrics`，并作为回调末尾 11 项（10 维分 + `eval_final_score`）回传后端。

实现：[`SingleProductEval/report_composite_score.py`](../SingleProductEval/report_composite_score.py)  
接入：[`eval_job_service.run_report_eval_job`](../SingleProductEval/eval_job_service.py)

### 公式

```
综合分 = Σ(维度档位分 × 0.2)   # 五维权重相等，等价于算术平均
理论最高分 = 100（五维档位满分均为 100）
```

### 顶层字段

| 字段 | 含义 |
|------|------|
| `eval_final_score` | 五维加权后的最终综合分（= 五维 contribution 之和） |
| `eval_max_score` | 理论最高分（固定 100） |
| `dimensions` | 五个维度的 `raw` / `score` / `weight` / `contribution` 明细 |

### Offer 范围

所有与 offer 相关的维度均使用 **全量 offer**（[`metrics._get_offers`](../SingleProductEval/metrics.py) = `priceComparison.offers` 全部条目）。

### 五维度定义

| 维度 id | 权重 | 原始值 | 分层规则 |
|---------|------|--------|----------|
| `platform_count` | 0.2 | 全量 offer 去重平台数 | ≥5→100，4→80，3→60，2→20，1→0 |
| `offer_count` | 0.2 | 全量 offer 条数 | ≥15→100，10–14→70，8–9→50，5–7→50，<5→0 |
| `offer_info_accuracy` | 0.2 | 链接逐 offer 准确率（价格侧暂时停用） | 100%→100，≥90%→80，≥80%→60，<80%→0 |
| `product_info_accuracy` | 0.2 | 图片结构 + 规格展示准确率 | =100%→100，否则→0 |
| `section_completeness` | 0.2 | 6 版块齐全数 ÷ 6 | 100%→100，≥80%→50，≥65%→20，<65%→0 |

### 维度细则

**Offer 信息准确率（仅链接）**

- 分母：全部 offer
- 单条正确：链接正确（KR3-8）
- KR3-11 价格侧暂时停用，不再参与交集；`degraded` 固定为 `false`

**商品信息准确率**

- 图片：KR3-1 结构校验（`images[]` 非空且 URL 合法），见 `validate_images_structure`
- 规格：`sku_spec_display_accuracy`（全量 offer，`variant_attributes` 完整性）
- 合并：图片通过且规格准确率 = 100% 时原始值 1.0，否则 < 1.0（二值分层得 0 分）

**版块完整率（6 版块）**

| 版块 | 判定 |
|------|------|
| 优惠 | `priceComparison.couponCodes.coupons` 非空 list |
| 返利 | `priceComparison.rebatesAndCoupons` 非空 list |
| 评论 | `reviews` 有实质内容 |
| 社媒 | `socialMediaFeedback` 有实质内容 |
| 测评 | `expertReviews` 有实质内容 |
| 属性 | `specifications` 有实质内容 |

### 输出示例

```json
{
  "composite_score": {
    "eval_final_score": 60.0,
    "eval_max_score": 100,
    "dimensions": {
      "platform_count": { "raw": 4, "score": 80, "weight": 0.2, "contribution": 16.0 },
      "offer_count": { "raw": 12, "score": 70, "weight": 0.2, "contribution": 14.0 },
      "offer_info_accuracy": {
        "raw": 0.5,
        "score": 0,
        "weight": 0.2,
        "contribution": 0.0,
        "degraded": false
      },
      "product_info_accuracy": {
        "raw": 1.0,
        "score": 100,
        "weight": 0.2,
        "contribution": 20.0
      },
      "section_completeness": {
        "raw": 0.8333,
        "present": 5,
        "score": 50,
        "weight": 0.2,
        "contribution": 10.0,
        "sections": { "coupon": true, "rebate": false, "...": true }
      }
    }
  }
}
```
