import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import main as api_main
from application.datasets.models import DatasetColumnProfile, DatasetIssue, DatasetProfile, DatasetSheetProfile
from application.datasets.service import DatasetService


class FailingCompleteUploadService(DatasetService):
    def complete_upload(
        self,
        version_id: str,
        *,
        storage_key: str,
        size_bytes: int,
        checksum_sha256: str,
        file_format: str,
    ):
        raise RuntimeError("storage metadata commit failed")


class DatasetApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_analyses_db = api_main.ANALYSES_DB
        self.original_datasets_db = api_main.DATASETS_DB
        self.original_uploads_root = api_main.UPLOADS_ROOT
        self.original_max_upload_bytes = api_main.MAX_UPLOAD_BYTES
        self.original_initialized = api_main._db_initialized
        api_main.ANALYSES_DB = os.path.join(self.tmpdir.name, "analyses.sqlite")
        api_main.DATASETS_DB = os.path.join(self.tmpdir.name, "datasets.sqlite")
        api_main.UPLOADS_ROOT = os.path.join(self.tmpdir.name, "uploads")
        api_main.MAX_UPLOAD_BYTES = 64
        api_main._db_initialized = False
        api_main._mutation_rate_log.clear()
        api_main._poll_rate_log.clear()
        self.client = TestClient(api_main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        api_main.ANALYSES_DB = self.original_analyses_db
        api_main.DATASETS_DB = self.original_datasets_db
        api_main.UPLOADS_ROOT = self.original_uploads_root
        api_main.MAX_UPLOAD_BYTES = self.original_max_upload_bytes
        api_main._db_initialized = self.original_initialized
        api_main._mutation_rate_log.clear()
        api_main._poll_rate_log.clear()
        self.tmpdir.cleanup()

    def test_get_default_workspace(self):
        response = self.client.get("/api/v1/workspaces/default")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "default")

    def test_upload_dataset_success(self):
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"date,sales\n2026-07-01,10\n", "text/csv")},
            data={"display_name": "Sales"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dataset"]["display_name"], "Sales")
        self.assertEqual(payload["version"]["status"], "profiling")
        self.assertEqual(payload["version"]["size_bytes"], len(b"date,sales\n2026-07-01,10\n"))
        self.assertNotIn("storage_key", payload["version"])

        ready = self._wait_for_version_status(payload["version"]["id"], {"ready"})
        self.assertEqual(ready["status"], "ready")

    def test_list_datasets_after_successful_upload(self):
        upload = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"date,sales\n2026-07-01,10\n", "text/csv")},
            data={"display_name": "Sales"},
        )

        self.assertEqual(upload.status_code, 200)
        self._wait_for_version_status(upload.json()["version"]["id"], {"ready"})

        response = self.client.get("/api/v1/workspaces/default/datasets")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["datasets"]), 1)
        self.assertEqual(payload["datasets"][0]["display_name"], "Sales")
        self.assertEqual(len(payload["datasets"][0]["versions"]), 1)
        self.assertEqual(payload["datasets"][0]["versions"][0]["status"], "ready")

    def test_upload_rejects_unsupported_type(self):
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.xls", b"date,sales\n2026-07-01,10\n", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 415)

        listed = self.client.get("/api/v1/workspaces/default/datasets")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["datasets"], [])

    def test_upload_rejects_oversize(self):
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={
                "file": (
                    "sales.csv",
                    b"date,sales\n2026-07-01,10\n2026-07-02,11\n2026-07-03,12\n2026-07-04,13\n",
                    "text/csv",
                )
            },
        )

        self.assertEqual(response.status_code, 413)

        listed = self.client.get("/api/v1/workspaces/default/datasets")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["datasets"], [])

    def test_upload_rejects_empty_file(self):
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"", "text/csv")},
        )

        self.assertEqual(response.status_code, 400)

    def test_delete_unknown_version_returns_not_found(self):
        response = self.client.delete("/api/v1/dataset-versions/unknown")

        self.assertEqual(response.status_code, 404)

    def test_get_profile_returns_issues(self):
        upload = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"date,sales\n2026-07-01,10\n", "text/csv")},
        )
        self.assertEqual(upload.status_code, 200)
        version_id = upload.json()["version"]["id"]
        self._wait_for_version_status(version_id, {"ready"})
        repository = self.client.app.state.dataset_repository_factory()
        version = repository.get_dataset_version(version_id)
        self.assertIsNotNone(version)
        assert version is not None
        version.status = "invalid"
        version.profile = DatasetProfile(
            format="csv",
            sheets=[
                DatasetSheetProfile(
                    name="__root__",
                    row_count=0,
                    columns=[
                        DatasetColumnProfile(
                            name="date",
                            inferred_type="string",
                            null_ratio=1.0,
                            unique_count=0,
                            examples=[],
                        )
                    ],
                )
            ],
        )
        version.issues = [DatasetIssue(code="bad-header", message="Missing header", severity="error")]
        repository.save_dataset_version(version)

        response = self.client.get(f"/api/v1/dataset-versions/{version_id}/profile")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["issues"][0]["code"], "bad-header")

    def test_upload_failure_after_blob_commit_cleans_orphan_blob_and_dataset(self):
        original_factory = self.client.app.state.dataset_service_factory
        repository_factory = self.client.app.state.dataset_repository_factory
        dispatcher = self.client.app.state.dataset_job_dispatcher

        def failing_factory():
            return FailingCompleteUploadService(repository_factory(), dispatcher)

        self.client.app.state.dataset_service_factory = failing_factory
        try:
            response = self.client.post(
                "/api/v1/workspaces/default/datasets",
                files={"file": ("sales.csv", b"date,sales\n2026-07-01,10\n", "text/csv")},
            )
        finally:
            self.client.app.state.dataset_service_factory = original_factory

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Internal dataset operation failed")
        listed = self.client.get("/api/v1/workspaces/default/datasets")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["datasets"], [])
        uploads_root = Path(api_main.UPLOADS_ROOT)
        blob_files = [path for path in uploads_root.rglob("*") if path.is_file()]
        self.assertEqual(blob_files, [])

    def test_upload_strips_client_filesystem_path_from_filename(self):
        boundary = "dataset-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="C:\\\\secret.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode("utf-8") + b"date,sales\n2026-07-01,10\n\r\n" + f"--{boundary}--\r\n".encode("utf-8")
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"]["original_filename"], "secret.csv")
        self.assertNotIn("\\", payload["version"]["original_filename"])

    def test_profile_polling_is_not_limited_by_mutation_threshold(self):
        upload = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"date,sales\n2026-07-01,10\n", "text/csv")},
        )
        self.assertEqual(upload.status_code, 200)
        version_id = upload.json()["version"]["id"]

        last_response = None
        for _ in range(20):
            last_response = self.client.get(f"/api/v1/dataset-versions/{version_id}/profile")
        self.assertIsNotNone(last_response)
        assert last_response is not None
        self.assertNotEqual(last_response.status_code, 429)

    def _wait_for_version_status(self, version_id: str, expected_statuses: set[str], timeout: float = 3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = self.client.get(f"/api/v1/dataset-versions/{version_id}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            if payload["status"] in expected_statuses:
                return payload
            time.sleep(0.05)
        self.fail(f"Version {version_id} did not reach {expected_statuses} before timeout")
