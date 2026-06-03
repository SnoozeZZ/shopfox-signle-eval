"""
HTTP entrypoint for the SingleProduct eval service.

Run from project root:
    uvicorn api_server:app --reload --port 5090
"""

from __future__ import annotations

from fastapi import FastAPI

from SingleProductEval.api_routes import eval_router
from SingleProductEval.env import load_env

load_env()

app = FastAPI(
    title="SingleProduct Eval API",
    description="PriceFox single-product report evaluation service",
    version="1.0.0",
)

app.include_router(eval_router, prefix="/api/eval", tags=["eval"])


@app.get("/health")
async def health():
    return {"status": "ok"}
