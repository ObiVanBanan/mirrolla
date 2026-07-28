import unittest
from unittest.mock import MagicMock, patch

from agent.executor import execute, _extract_json_from_text
from agent.planner import _build_messages, plan
from agent.runtime.execution_manifest import ExecutionDatasetReference, ExecutionManifest
from agent.schemas import AnalysisPlan, PeriodSpec, RoutingResult, SkillType
from application.datasets.execution import ResolvedDatasetInput
from application.datasets.models import DatasetColumnProfile, DatasetProfile, DatasetSheetProfile


class ExecutorBaselineTests(unittest.TestCase):
    def _profile(self) -> DatasetProfile:
        return DatasetProfile(
            format="csv",
            sheets=[
                DatasetSheetProfile(
                    name="__root__",
                    row_count=2,
                    sampled=False,
                    columns=[
                        DatasetColumnProfile(
                            name="date",
                            inferred_type="string",
                            null_ratio=0.0,
                            unique_count=2,
                            examples=["2026-07-01", "2026-07-02"],
                        ),
                        DatasetColumnProfile(
                            name="sales",
                            inferred_type="integer",
                            null_ratio=0.0,
                            unique_count=2,
                            examples=["10", "11"],
                            min_value="10",
                            max_value="11",
                        ),
                    ],
                )
            ],
        )

    def _plan(self) -> AnalysisPlan:
        return AnalysisPlan(
            skill=SkillType.SALES_DECLINE,
            question="Почему упали продажи?",
            product_codes=[],
            period=PeriodSpec(current_days=14, comparison="previous_equal_period"),
            hypotheses=[],
            limitations=[],
        )

    def test_extract_json_from_markdown_block(self):
        payload = """
```json
{"answer_status":"answered","answer":"ok","findings":[{"entity_id":"A1","reasons":["r"],"metrics":{"change_pct":-10}}]}
```
"""
        parsed = _extract_json_from_text(payload)
        self.assertEqual(parsed["answer"], "ok")
        self.assertEqual(parsed["findings"][0]["entity_id"], "A1")

    def test_extract_json_ignores_js_comments(self):
        payload = """
```json
{
  // comment
  "answer_status": "partial",
  "answer": "ok",
  "findings": []
}
```
"""
        parsed = _extract_json_from_text(payload)
        self.assertEqual(parsed["answer_status"], "partial")

    @patch("agent.planner.API_KEY", "")
    def test_planner_fallback_without_api_key(self):
        routing = RoutingResult(
            skill=SkillType.SALES_DECLINE,
            product_codes=["ЦБ-00007397"],
            period_days=14,
        )
        result = plan("Почему упали продажи ЦБ-00007397?", routing=routing)
        self.assertEqual(result.skill, SkillType.SALES_DECLINE)
        self.assertEqual(result.period.current_days, 14)
        self.assertGreaterEqual(len(result.hypotheses), 4)

    def test_planner_messages_include_profile_context_without_raw_rows(self):
        routing = RoutingResult(
            skill=SkillType.SALES_DECLINE,
            product_codes=[],
            period_days=14,
        )
        dataset_context = [
            ResolvedDatasetInput(
                position=0,
                dataset_id="dataset-1",
                dataset_version_id="version-1",
                display_name="Sales",
                original_filename="sales.csv",
                format="csv",
                checksum_sha256="sum-1",
                storage_key="default/.blobs/sum-1",
                profile=self._profile(),
                status="ready",
            )
        ]

        messages = _build_messages("Почему упали продажи?", routing, dataset_context)

        self.assertIn("dataset_version_id=version-1", messages[0]["content"])
        self.assertIn("column: date", messages[0]["content"])
        self.assertIn("examples=2026-07-01, 2026-07-02", messages[0]["content"])
        self.assertNotIn("2026-07-01,10", messages[0]["content"])

    @patch("agent.executor._execute_legacy", side_effect=AssertionError("legacy should not run"))
    @patch("agent.reporter.synthesize", return_value="summary")
    @patch("agent.executor._parse_ci_result")
    @patch("agent.ci_runner.CIRunner.run_analysis")
    def test_execute_with_manifest_uses_provided_files_only(
        self,
        run_analysis,
        parse_ci_result,
        _reporter,
        _legacy,
    ):
        run_analysis.return_value = {"status": "completed", "text": "{}", "charts": [], "error": ""}
        parse_ci_result.return_value = ([], [], "answered", "ok", [])
        manifest = ExecutionManifest(
            analysis_id="analysis-1",
            question="Почему упали продажи?",
            skill_id=SkillType.SALES_DECLINE.value,
            datasets=[
                ExecutionDatasetReference(
                    position=0,
                    dataset_id="dataset-1",
                    dataset_version_id="version-1",
                    display_name="Sales",
                    original_filename="sales.csv",
                    sandbox_filename="dataset_001.csv",
                    format="csv",
                    checksum_sha256="sum-1",
                    profile=self._profile(),
                )
            ],
        )

        result = execute(
            self._plan(),
            analysis_id="analysis-1",
            execution_manifest=manifest,
            file_paths=["C:/tmp/dataset_001.csv"],
        )

        self.assertEqual(run_analysis.call_args.kwargs["file_paths"], ["C:/tmp/dataset_001.csv"])
        self.assertNotIn("balances.json", run_analysis.call_args.kwargs["prompt"])
        self.assertNotIn("DATA_SCHEMA", run_analysis.call_args.kwargs["prompt"])
        self.assertEqual(result.execution_metadata.datasets[0].dataset_version_id, "version-1")
        self.assertEqual(result.execution_metadata.datasets[0].checksum_sha256, "sum-1")
        self.assertNotIn("storage_key", result.model_dump(mode="json"))

    @patch("agent.executor._execute_legacy")
    def test_execute_without_manifest_keeps_legacy_compatibility(self, legacy_execute):
        legacy_execute.return_value = MagicMock()

        execute(self._plan())

        legacy_execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
