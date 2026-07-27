import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.schemas import AnalysisPlan, PeriodSpec, SkillType
from api import main as api_main


class ApiTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        api_main.ANALYSES_DB = os.path.join(self.tmpdir.name, "analyses.sqlite")
        api_main._db_initialized = False
        self.client = TestClient(api_main.app)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _plan(self, question: str) -> AnalysisPlan:
        return AnalysisPlan(
            skill=SkillType.SALES_DECLINE,
            question=question,
            product_codes=[],
            period=PeriodSpec(current_days=14, comparison="previous_equal_period"),
            hypotheses=[],
            limitations=[],
        )

    @patch("api.main.generate_plan")
    @patch("api.main.route_sync")
    def test_create_accepts_legacy_question_only_payload(self, route_sync, generate_plan):
        route_sync.return_value = type("Routing", (), {
            "skill": SkillType.SALES_DECLINE,
            "product_codes": [],
            "period_days": 14,
        })()
        generate_plan.side_effect = lambda question, routing=None: self._plan(question)

        created = self.client.post(
            "/api/v1/analyses",
            json={"question": "Почему упали продажи?"},
        )

        self.assertEqual(created.status_code, 200)
        payload = created.json()
        self.assertEqual(payload["question"], "Почему упали продажи?")
        self.assertEqual(payload["status"], "awaiting_approval")
        self.assertIn("plan", payload)

    @patch("api.main.generate_plan")
    @patch("api.main.route_sync")
    def test_create_and_revise_and_reject_flow(self, route_sync, generate_plan):
        route_sync.return_value = type("Routing", (), {
            "skill": SkillType.SALES_DECLINE,
            "product_codes": [],
            "period_days": 14,
        })()
        generate_plan.side_effect = lambda question, routing=None: self._plan(question)

        created = self.client.post("/api/v1/analyses", json={"question": "Почему упали продажи?"})
        self.assertEqual(created.status_code, 200)
        analysis_id = created.json()["id"]
        self.assertEqual(created.json()["status"], "awaiting_approval")

        revised = self.client.post(
            f"/api/v1/analyses/{analysis_id}/revise",
            json={"feedback": "период 30 дней"},
        )
        self.assertEqual(revised.status_code, 200)
        self.assertEqual(revised.json()["status"], "awaiting_approval")

        rejected = self.client.post(f"/api/v1/analyses/{analysis_id}/reject")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
