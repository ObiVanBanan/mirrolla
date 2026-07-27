import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from api import main as api_main


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
        api_main.MAX_UPLOAD_BYTES = 4
        api_main._db_initialized = False
        api_main._rate_log.clear()
        self.client = TestClient(api_main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        api_main.ANALYSES_DB = self.original_analyses_db
        api_main.DATASETS_DB = self.original_datasets_db
        api_main.UPLOADS_ROOT = self.original_uploads_root
        api_main.MAX_UPLOAD_BYTES = self.original_max_upload_bytes
        api_main._db_initialized = self.original_initialized
        api_main._rate_log.clear()
        self.tmpdir.cleanup()

    def test_get_default_workspace(self):
        response = self.client.get("/api/v1/workspaces/default")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "default")

    def test_upload_dataset_success(self):
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"abcd", "text/csv")},
            data={"display_name": "Sales"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dataset"]["display_name"], "Sales")
        self.assertEqual(payload["version"]["status"], "profiling")
        self.assertEqual(payload["version"]["size_bytes"], 4)

    def test_upload_rejects_unsupported_type(self):
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.xls", b"abcd", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 415)

    def test_upload_rejects_oversize(self):
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            files={"file": ("sales.csv", b"abcde", "text/csv")},
        )

        self.assertEqual(response.status_code, 413)

    def test_upload_strips_client_filesystem_path_from_filename(self):
        boundary = "dataset-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="C:\\\\secret.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode("utf-8") + b"abcd\r\n" + f"--{boundary}--\r\n".encode("utf-8")
        response = self.client.post(
            "/api/v1/workspaces/default/datasets",
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"]["original_filename"], "secret.csv")
        self.assertNotIn("\\", payload["version"]["original_filename"])
        self.assertNotIn("secret.csv", payload["version"]["storage_key"])
