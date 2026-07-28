"""Versioned skill metadata for the exemplar runtime."""

from __future__ import annotations

from agent.schemas import SkillType
from agent.runtime.contracts import SkillMetadata


_SALES_DECLINE_METADATA = SkillMetadata(
    skill_id=SkillType.SALES_DECLINE.value,
    version="1.0.0",
    required_concepts=[
        "product_identifier",
        "product_name",
        "order_date",
        "order_status",
        "order_identifier",
    ],
    optional_concepts=[
        "review_text",
        "rating",
        "inventory_balance",
        "category_name",
    ],
    output_contract_version="execution_result/v2",
    validator_id="sales_decline_v1",
    reference_helpers=["sales.py", "stocks.py", "reviews.py"],
)


def load_skill_metadata(skill: SkillType) -> SkillMetadata:
    if skill == SkillType.SALES_DECLINE:
        return _SALES_DECLINE_METADATA
    raise ValueError(f"Versioned runtime metadata is not defined for {skill.value}")

