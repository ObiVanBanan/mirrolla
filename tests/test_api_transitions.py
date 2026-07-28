import os
import tempfile
import time
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.schemas import AnalysisPlan, PeriodSpec, SkillType
from api import main as api_main
from application.datasets.models import Dataset, DatasetVersion


class ApiTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db = api_main.ANALYSES_DB
        self.original_datasets_db = api_main.DATASETS_DB
        self.original_uploads_root = api_main.UPLOADS_ROOT
        self.original_initialized = api_main._db_initialized
        api_main.ANALYSES_DB = os.path.join(self.tmpdir.name, "analyses.sqlite")
        api_main.DATASETS_DB = os.path.join(self.tmpdir.name, "datasets.sqlite")
        api_main.UPLOADS_ROOT = os.path.join(self.tmpdir.name, "uploads")
        api_main._db_initialized = False
        api_main._rate_log.clear()
        api_main._poll_rate_log.clear()
        self.client = TestClient(api_main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        api_main.ANALYSES_DB = self.original_db
        api_main.DATASETS_DB = self.original_datasets_db
        api_main.UPLOADS_ROOT = self.original_uploads_root
        api_main._db_initialized = self.original_initialized
        api_main._rate_log.clear()
        api_main._poll_rate_log.clear()
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

    @patch("api.main.generate_plan")
    @patch("api.main.route_sync")
    def test_create_persists_selected_dataset_version_ids(self, route_sync, generate_plan):
        route_sync.return_value = type("Routing", (), {
            "skill": SkillType.SALES_DECLINE,
            "product_codes": [],
            "period_days": 14,
        })()
        generate_plan.side_effect = lambda question, routing=None: self._plan(question)

        upload = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"date,sales\n2026-07-01,10\n", "text/csv")},
            data={"display_name": "Sales"},
        )
        self.assertEqual(upload.status_code, 200)
        version_id = upload.json()["version"]["id"]

        deadline = time.time() + 3.0
        while time.time() < deadline:
            current = self.client.get(f"/api/v1/dataset-versions/{version_id}")
            self.assertEqual(current.status_code, 200)
            if current.json()["status"] == "ready":
                break
            time.sleep(0.05)
        else:
            self.fail("Dataset version did not become ready")

        created = self.client.post(
            "/api/v1/analyses",
            json={
                "question": "Почему упали продажи?",
                "dataset_version_ids": [version_id],
            },
        )

        self.assertEqual(created.status_code, 200)
        payload = created.json()
        self.assertEqual(payload["dataset_version_ids"], [version_id])
        self.assertEqual(len(payload["dataset_attachments"]), 1)
        self.assertEqual(payload["dataset_attachments"][0]["dataset_version_id"], version_id)
        self.assertEqual(payload["dataset_attachments"][0]["display_name"], "Sales")
        self.assertEqual(payload["dataset_attachments"][0]["original_filename"], "sales.csv")

        fetched = self.client.get(f"/api/v1/analyses/{payload['id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["dataset_version_ids"], [version_id])
        self.assertEqual(
            fetched.json()["dataset_attachments"][0]["dataset_version_id"],
            version_id,
        )

    @patch("api.main.generate_plan")
    @patch("api.main.route_sync")
    def test_create_rejects_non_ready_dataset_version_selection(self, route_sync, generate_plan):
        route_sync.return_value = type("Routing", (), {
            "skill": SkillType.SALES_DECLINE,
            "product_codes": [],
            "period_days": 14,
        })()
        generate_plan.side_effect = lambda question, routing=None: self._plan(question)

        repository = self.client.app.state.dataset_repository_factory()
        now = datetime.now(UTC)
        dataset = repository.save_dataset(
            Dataset(
                id="dataset_pending",
                workspace_id="default",
                display_name="Sales",
                source_type="upload",
                created_at=now,
            )
        )
        version_id = repository.save_dataset_version(
            DatasetVersion(
                id="version_pending",
                dataset_id=dataset.id,
                original_filename="sales.csv",
                storage_key="default/.blobs/pending",
                format="csv",
                size_bytes=24,
                checksum_sha256="abc123",
                status="uploaded",
                created_at=now,
            )
        ).id

        created = self.client.post(
            "/api/v1/analyses",
            json={
                "question": "Почему упали продажи?",
                "dataset_version_ids": [version_id],
            },
        )

        self.assertEqual(created.status_code, 409)

    @patch("api.main.generate_plan")
    @patch("api.main.route_sync")
    def test_create_deduplicates_dataset_version_ids_preserving_order(self, route_sync, generate_plan):
        route_sync.return_value = type("Routing", (), {
            "skill": SkillType.SALES_DECLINE,
            "product_codes": [],
            "period_days": 14,
        })()
        generate_plan.side_effect = lambda question, routing=None: self._plan(question)

        repository = self.client.app.state.dataset_repository_factory()
        now = datetime.now(UTC)
        first_dataset = repository.save_dataset(
            Dataset(
                id="dataset_first",
                workspace_id="default",
                display_name="First",
                source_type="upload",
                created_at=now,
            )
        )
        second_dataset = repository.save_dataset(
            Dataset(
                id="dataset_second",
                workspace_id="default",
                display_name="Second",
                source_type="upload",
                created_at=now,
            )
        )
        first_version = repository.save_dataset_version(
            DatasetVersion(
                id="version_first",
                dataset_id=first_dataset.id,
                original_filename="first.csv",
                storage_key="default/.blobs/first",
                format="csv",
                size_bytes=24,
                checksum_sha256="111",
                status="ready",
                created_at=now,
            )
        )
        second_version = repository.save_dataset_version(
            DatasetVersion(
                id="version_second",
                dataset_id=second_dataset.id,
                original_filename="second.csv",
                storage_key="default/.blobs/second",
                format="csv",
                size_bytes=24,
                checksum_sha256="222",
                status="ready",
                created_at=now,
            )
        )

        created = self.client.post(
            "/api/v1/analyses",
            json={
                "question": "РџРѕС‡РµРјСѓ СѓРїР°Р»Рё РїСЂРѕРґР°Р¶Рё?",
                "dataset_version_ids": [
                    second_version.id,
                    first_version.id,
                    second_version.id,
                    first_version.id,
                ],
            },
        )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(
            created.json()["dataset_version_ids"],
            [second_version.id, first_version.id],
        )
        self.assertEqual(
            [item["dataset_version_id"] for item in created.json()["dataset_attachments"]],
            [second_version.id, first_version.id],
        )

    @patch("api.main.generate_plan")
    @patch("api.main.route_sync")
    def test_new_upload_does_not_change_existing_analysis_selection(self, route_sync, generate_plan):
        route_sync.return_value = type("Routing", (), {
            "skill": SkillType.SALES_DECLINE,
            "product_codes": [],
            "period_days": 14,
        })()
        generate_plan.side_effect = lambda question, routing=None: self._plan(question)

        first_upload = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales-v1.csv", b"date,sales\n2026-07-01,10\n", "text/csv")},
            data={"display_name": "Sales"},
        )
        self.assertEqual(first_upload.status_code, 200)
        dataset_id = first_upload.json()["dataset"]["id"]
        first_version_id = first_upload.json()["version"]["id"]

        deadline = time.time() + 3.0
        while time.time() < deadline:
            current = self.client.get(f"/api/v1/dataset-versions/{first_version_id}")
            self.assertEqual(current.status_code, 200)
            if current.json()["status"] == "ready":
                break
            time.sleep(0.05)
        else:
            self.fail("First dataset version did not become ready")

        created = self.client.post(
            "/api/v1/analyses",
            json={
                "question": "РџРѕС‡РµРјСѓ СѓРїР°Р»Рё РїСЂРѕРґР°Р¶Рё?",
                "dataset_version_ids": [first_version_id],
            },
        )
        self.assertEqual(created.status_code, 200)
        analysis_id = created.json()["id"]

        second_upload = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales-v2.csv", b"date,sales\n2026-07-02,20\n", "text/csv")},
            data={"dataset_id": dataset_id},
        )
        self.assertEqual(second_upload.status_code, 200)
        second_version_id = second_upload.json()["version"]["id"]

        deadline = time.time() + 3.0
        while time.time() < deadline:
            current = self.client.get(f"/api/v1/dataset-versions/{second_version_id}")
            self.assertEqual(current.status_code, 200)
            if current.json()["status"] == "ready":
                break
            time.sleep(0.05)
        else:
            self.fail("Second dataset version did not become ready")

        fetched = self.client.get(f"/api/v1/analyses/{analysis_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["dataset_version_ids"], [first_version_id])
        self.assertEqual(
            [item["dataset_version_id"] for item in fetched.json()["dataset_attachments"]],
            [first_version_id],
        )
        self.assertEqual(
            fetched.json()["dataset_attachments"][0]["original_filename"],
            "sales-v1.csv",
        )


if __name__ == "__main__":
    unittest.main()
