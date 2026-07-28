"""Deterministic semantic mapping based on dataset profiles."""

from __future__ import annotations

from agent.runtime.contracts import DatasetProfile, SemanticFieldBinding, SkillMetadata


ALIASES: dict[str, tuple[str, ...]] = {
    "product_identifier": ("product_code", "Артикул", "Артикул продавца", "code"),
    "product_name": ("product_name", "Название товара", "name", "catalog_name"),
    "order_date": ("date", "Дата публикации", "Дата"),
    "order_status": ("order_status", "Статус получения"),
    "order_identifier": ("order_id", "Номер заказа"),
    "review_text": ("review_text", "Текст отзыва", "text"),
    "rating": ("rating", "Оценка", "Количество звезд"),
    "inventory_balance": ("balance",),
    "category_name": ("product_type", "productType"),
}


def build_semantic_mapping(
    profiles: list[DatasetProfile],
    metadata: SkillMetadata,
) -> tuple[list[SemanticFieldBinding], list[str]]:
    bindings: list[SemanticFieldBinding] = []
    missing_required: list[str] = []

    available_concepts = list(metadata.required_concepts) + list(metadata.optional_concepts)
    for concept in available_concepts:
        aliases = ALIASES.get(concept, ())
        bound = None
        for dataset in profiles:
            for file_profile in dataset.files:
                for column in file_profile.columns:
                    if column.name in aliases:
                        bound = SemanticFieldBinding(
                            concept=concept,
                            dataset_id=dataset.dataset_id,
                            column_name=column.name,
                            confidence=1.0,
                            required=concept in metadata.required_concepts,
                            reason="deterministic alias match",
                        )
                        break
                if bound:
                    break
            if bound:
                break
        if bound:
            bindings.append(bound)
        elif concept in metadata.required_concepts:
            missing_required.append(concept)

    return bindings, missing_required

