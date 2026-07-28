import os
import unittest

from agent.runtime.manifest_builder import build_manifest
from agent.runtime.profiler import profile_datasets
from agent.runtime.semantic_mapper import build_semantic_mapping
from agent.runtime.skill_loader import load_skill_metadata
from agent.runtime.validation import validate_generic_result, validate_sales_decline_result
from agent.schemas import AnalysisPlan, Hypothesis, PeriodSpec, SkillType


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


class RuntimeTests(unittest.TestCase):
    def _plan(self) -> AnalysisPlan:
        return AnalysisPlan(
            skill=SkillType.SALES_DECLINE,
            question="Почему упали продажи ЦБ-00007397?",
            product_codes=["ЦБ-00007397"],
            period=PeriodSpec(current_days=14, comparison="previous_equal_period"),
            hypotheses=[
                Hypothesis(
                    id="H1",
                    title="Дефицит остатков",
                    datasets=["sales", "stocks"],
                    method="Проверить остатки",
                    helpers=["compare_periods", "stockout_days"],
                )
            ],
            limitations=["Нет цен"],
        )

    def test_profiles_and_mapping_cover_required_concepts(self):
        metadata = load_skill_metadata(SkillType.SALES_DECLINE)
        profiles = profile_datasets(PROJECT_ROOT, ["sales", "stocks", "categories", "reviews_wb"])
        bindings, missing = build_semantic_mapping(profiles, metadata)
        self.assertFalse(missing)
        concepts = {binding.concept for binding in bindings}
        self.assertIn("product_identifier", concepts)
        self.assertIn("order_date", concepts)

    def test_manifest_and_validators(self):
        plan = self._plan()
        metadata = load_skill_metadata(SkillType.SALES_DECLINE)
        profiles = profile_datasets(PROJECT_ROOT, ["sales", "stocks"])
        bindings, missing = build_semantic_mapping(profiles, metadata)
        self.assertFalse(missing)
        manifest = build_manifest(plan, metadata, profiles, bindings)

        parsed = {
            "answer_status": "answered",
            "answer": "Продажи упали из-за остатков",
            "findings": [
                {
                    "entity_type": "product",
                    "entity_id": "ЦБ-00007397",
                    "name": "Товар",
                    "priority": "high",
                    "reasons": ["Продажи упали с 10 до 5 (-50%)"],
                    "metrics": {"sales_current": 5, "sales_previous": 10, "change_pct": -50.0},
                    "recommended_action": "Проверить остатки",
                }
            ],
            "limitations": [],
        }
        generic_report = validate_generic_result(parsed, manifest)
        sales_report = validate_sales_decline_result(parsed, manifest)
        self.assertTrue(generic_report.valid)
        self.assertTrue(sales_report.valid)


if __name__ == "__main__":
    unittest.main()

