"""Logical dataset registry for the exemplar runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetEntry:
    dataset_id: str
    logical_name: str
    relative_paths: tuple[str, ...]


REGISTRY: dict[str, DatasetEntry] = {
    "sales": DatasetEntry(
        dataset_id="sales",
        logical_name="Ozon orders and embedded reviews",
        relative_paths=(
            "data/озон 17.03-16.04.xlsx",
            "data/озон 17.04-16.05.xlsx",
            "data/озон 17.05-16.06.xlsx",
        ),
    ),
    "reviews_wb": DatasetEntry(
        dataset_id="reviews_wb",
        logical_name="WB reviews",
        relative_paths=("data/Отзывы ВБ 17.03-17.06.2026.xlsx",),
    ),
    "categories": DatasetEntry(
        dataset_id="categories",
        logical_name="1C product catalog",
        relative_paths=("data/prepared/products.json",),
    ),
    "stocks": DatasetEntry(
        dataset_id="stocks",
        logical_name="1C product balances snapshot",
        relative_paths=("data/prepared/balances.json",),
    ),
}


def resolve_paths(project_root: str, dataset_id: str) -> list[str]:
    entry = REGISTRY[dataset_id]
    return [os.path.join(project_root, rel_path) for rel_path in entry.relative_paths]

