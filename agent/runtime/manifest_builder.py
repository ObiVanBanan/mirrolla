"""Execution manifest builder for exemplar runtime."""

from __future__ import annotations

from agent.schemas import AnalysisPlan
from agent.runtime.contracts import DatasetProfile, ExecutionManifest, SemanticFieldBinding, SkillMetadata


def build_manifest(
    plan: AnalysisPlan,
    metadata: SkillMetadata,
    profiles: list[DatasetProfile],
    bindings: list[SemanticFieldBinding],
) -> ExecutionManifest:
    return ExecutionManifest(
        question=plan.question,
        skill_id=metadata.skill_id,
        skill_version=metadata.version,
        plan_version="analysis_plan/v1",
        product_codes=list(plan.product_codes),
        current_period_days=plan.period.current_days,
        comparison_method=plan.period.comparison,
        datasets=profiles,
        semantic_bindings=bindings,
        hypotheses=[hypothesis.title for hypothesis in plan.hypotheses],
        limitations=list(plan.limitations),
        expected_output_contract=metadata.output_contract_version,
        runtime_restrictions=[
            "use only profiled datasets and mapped columns",
            "do not invent missing business concepts",
            "return honest limitations for unavailable data",
            "bounded repair maximum: 2 attempts",
        ],
    )

