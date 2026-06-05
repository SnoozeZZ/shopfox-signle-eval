# PriceFox 单商品报告评测服务

对 Agent 生成的单商品比价报告进行自动化指标计算，并将结果回传给后端。

- **输入**：后端提交的 `report_content`（报告 JSON）+ 自动/手工构建的 GT（Ground Truth）
- **输出**：`result.json`（含 `metrics`、`raw_metrics`）+ 可选 **external-callback** 推送

指标 id、计算公式、回调契约详见 **[docs/METRICS.md](docs/METRICS.md)**（以代码为准）。

---

## 环境要求

| 项 | 说明 |
|----|------|
| Python | 3.11+（本地开发） |
| Docker | 生产部署（Docker Compose） |
| `DASHSCOPE_API_KEY` | 可选；KR3-9 SPU、KR3-13 返利 LLM 判定 |
| 价格爬虫 | 可选；KR3-11 价格准确率（见 `.env.example` 中 `CRAWLER_URL`） |
| 类目扩展爬虫 | 可选；KR4-5 Top3 链接完备率（`CRAWLER_API`） |

---

## 本地开发

```bash
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY 等

python -m venv .venv
source .venv/bin/activate
pip install -r requirements-prod.txt

uvicorn api_server:app --reload --port 5090
curl http://127.0.0.1:5090/health

pytest SingleProductEval/test_eval_callback_transform.py -q
```

---

## 生产部署

```bash
./deploy.sh
```

脚本会 rsync 代码到服务器（默认 `root@192.1.1.27:/root/hy/llm_eval_report`）、执行 `docker compose build && up -d`，并检查 `/health`。

**注意**：

- 服务器上的 `.env` **不会**被 rsync 覆盖，首次部署需在服务器 `REMOTE_DIR` 下自行配置
- 容器内监听 `5090`，宿主机端口由 `HOST_PORT` 控制（默认 `5090`）

常用覆盖：

```bash
SSH_KEY=~/.ssh/id_rsa ./deploy.sh
HOST_PORT=5090 SERVER_HOST=192.1.1.27 ./deploy.sh
```

查看日志：

```bash
ssh root@192.1.1.27 'cd /root/hy/llm_eval_report && docker compose logs -f'
```

---

## API 速览

基础 URL 示例：`http://<host>:5090`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/eval/report/submit` | 提交单报告评测（异步 job） |
| GET | `/api/eval/report/jobs/{run_id}/status` | 任务状态 |
| GET | `/api/eval/report/jobs/{run_id}/result` | 完整结果（`metrics`、`raw_metrics`、`callback_payload`） |

### 提交评测

`POST /api/eval/report/submit` 请求体主要字段：

- `run_id`：本次 Run 标识
- `report_id`：报告标识
- `search_term`：搜索词
- `report_content`：完整报告 JSON

任务完成后，结果写入 `SingleProductEval/eval_logs/backend_jobs/{run_id}/result.json`。

---

## 外部回调

配置项（`.env`）：

```env
EVAL_CALLBACK_ENABLED=true
EVAL_CALLBACK_URL=http://<backend>/v1/eval/runs/external-callback
EVAL_CALLBACK_TIMEOUT_SEC=60
```

回调 Body 结构：

```json
{
  "runId": "...",
  "reportId": "...",
  "searchTerm": "...",
  "metrics": [
    { "krId": "offer_price_accuracy", "value": "0.75", "valueType": "percentage", "passed": true, "reason": "" }
  ],
  "issues": [
    {
      "attributionKr": "offer_price_accuracy",
      "description": "Card shows $499, landing page $549 (Galaxy S25 Ultra · Amazon)",
      "priority": "P0",
      "section": "priceComparison",
      "link": "https://..."
    }
  ]
}
```

要点：

- **`metrics[].krId`** 与 **`issues[].attributionKr`** 使用**同一套 22 个对外指标 id**（字段名不同，取值相同）
- 回调固定输出全部 22 项指标；未算出时 `value=""`、`passed=false`
- `issues` 仅包含已证实的报告数据错误，不含评测系统失败、不可核验项

完整指标表、公式、issues 规则见 **[docs/METRICS.md](docs/METRICS.md)**。

---

## 目录结构

```
api_server.py              # FastAPI 入口
SingleProductEval/
  api_routes.py              # API 路由
  metrics.py                 # 指标计算主逻辑
  eval_callback_transform.py # 回调 payload 组装
  config.py                  # 指标注册、回调 id 白名单
  kr3_*_validator.py         # KR3 各子项校验
  eval_logs/                 # 任务与爬虫缓存（部署时挂载 volume）
deploy.sh
docker-compose.yml
docs/METRICS.md              # 指标手册
```

---

## 相关文档

- [docs/METRICS.md](docs/METRICS.md) — 全部计算指标、输出 id、公式、回调与 issues 说明
