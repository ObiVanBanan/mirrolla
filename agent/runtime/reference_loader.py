"""Load only relevant helper sources for prompt construction."""

from __future__ import annotations

import os

from agent.schemas import AnalysisPlan


HELPER_FILE_BY_FUNCTION: dict[str, str] = {
    "load_ozon": "sales.py",
    "normalize_ozon": "sales.py",
    "daily_order_counts": "sales.py",
    "compare_periods": "sales.py",
    "top_growth": "sales.py",
    "top_decline": "sales.py",
    "category_growth": "sales.py",
    "category_growth_by_type": "sales.py",
    "faster_than_market": "sales.py",
    "analyze_decline": "sales.py",
    "load_product_categories": "sales.py",
    "stockout_days": "stocks.py",
    "critical_stocks": "stocks.py",
    "out_of_stock": "stocks.py",
    "production_plan": "stocks.py",
    "load_wb_reviews": "reviews.py",
    "normalize_wb_reviews": "reviews.py",
    "negative_reviews_wb": "reviews.py",
    "negative_reviews_ozon": "reviews.py",
    "review_summary": "reviews.py",
    "reviews_requiring_response": "reviews.py",
    "recurring_complaints": "reviews.py",
}


def load_reference_code(helpers_dir: str, plan: AnalysisPlan) -> str:
    referenced_functions = {
        helper_name
        for hypothesis in plan.hypotheses
        for helper_name in hypothesis.helpers
    }
    referenced_files = sorted({
        HELPER_FILE_BY_FUNCTION[helper_name]
        for helper_name in referenced_functions
        if helper_name in HELPER_FILE_BY_FUNCTION
    })

    blocks: list[str] = []
    for file_name in referenced_files:
        path = os.path.join(helpers_dir, file_name)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            code = fh.read()
        blocks.append(f"### helpers/{file_name}\n```python\n{code}\n```")
    return "\n\n".join(blocks)

