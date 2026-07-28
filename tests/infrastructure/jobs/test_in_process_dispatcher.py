from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest

from application.datasets.jobs import DatasetProfileJobResult
from application.datasets.models import DatasetColumnProfile, DatasetProfile, DatasetSheetProfile
from application.datasets.service import DatasetService
from infrastructure.jobs.in_process_dispatcher import InProcessDatasetJobDispatcher
from infrastructure.persistence.sqlite_datasets import SqliteDatasetRepository


class InMemoryStorage:
    def open_read(self, storage_key: str):
        raise FileNotFoundError(storage_key)

    def put_stream(self, **kwargs):
        raise NotImplementedError

    def delete(self, storage_key: str) -> None:
        return None


class NoopDispatcher:
    def dispatch_profile(self, version_id: str) -> None:
        return None


class DispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "datasets.sqlite")
        self.repository = SqliteDatasetRepository(self.db_path)
        self.service = DatasetService(self.repository, NoopDispatcher())
        self.workspace = self.service.ensure_default_workspace()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_restart_with_profiling_version_re_dispatches_job(self) -> None:
        _, version = self.service.register_upload_receiving(
            self.workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/sales",
            size_bytes=10,
            checksum_sha256="sum-1",
            file_format="csv",
        )
        self.service.start_profiling(version.id)
        completed = threading.Event()

        def profiler(saved_version, storage):
            completed.set()
            return DatasetProfileJobResult(
                version_id=saved_version.id,
                profile=_profile(),
                issues=[],
                success=True,
            )

        dispatcher = InProcessDatasetJobDispatcher(
            repository_factory=lambda: SqliteDatasetRepository(self.db_path),
            storage_factory=InMemoryStorage,
            profiler=profiler,
            max_workers=1,
        )
        try:
            for queued in self.repository.list_dataset_versions_by_status(["profiling"]):
                dispatcher.dispatch_profile(queued.id)
            self.assertTrue(completed.wait(2.0))
        finally:
            dispatcher.shutdown()

        stored = self.repository.get_dataset_version(version.id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "ready")

    def test_dispatcher_limits_concurrent_jobs(self) -> None:
        version_ids = []
        for index in range(4):
            _, version = self.service.register_upload_receiving(
                self.workspace.id,
                original_filename=f"sales-{index}.csv",
            )
            self.service.complete_upload(
                version.id,
                storage_key=f"workspace/.blobs/{index}",
                size_bytes=10,
                checksum_sha256=f"sum-{index}",
                file_format="csv",
            )
            self.service.start_profiling(version.id)
            version_ids.append(version.id)

        active = 0
        max_seen = 0
        lock = threading.Lock()
        release = threading.Event()
        started = threading.Event()

        def profiler(saved_version, storage):
            nonlocal active, max_seen
            with lock:
                active += 1
                max_seen = max(max_seen, active)
                if active >= 2:
                    started.set()
            release.wait(2.0)
            with lock:
                active -= 1
            return DatasetProfileJobResult(
                version_id=saved_version.id,
                profile=_profile(),
                issues=[],
                success=True,
            )

        dispatcher = InProcessDatasetJobDispatcher(
            repository_factory=lambda: SqliteDatasetRepository(self.db_path),
            storage_factory=InMemoryStorage,
            profiler=profiler,
            max_workers=2,
        )
        try:
            for version_id in version_ids:
                dispatcher.dispatch_profile(version_id)
            self.assertTrue(started.wait(2.0))
            time.sleep(0.2)
            self.assertEqual(max_seen, 2)
        finally:
            release.set()
            dispatcher.shutdown()

    def test_profiler_exception_marks_invalid(self) -> None:
        _, version = self.service.register_upload_receiving(
            self.workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/error",
            size_bytes=10,
            checksum_sha256="sum-error",
            file_format="csv",
        )
        self.service.start_profiling(version.id)

        def profiler(saved_version, storage):
            raise RuntimeError("boom")

        dispatcher = InProcessDatasetJobDispatcher(
            repository_factory=lambda: SqliteDatasetRepository(self.db_path),
            storage_factory=InMemoryStorage,
            profiler=profiler,
            max_workers=1,
        )
        try:
            dispatcher.dispatch_profile(version.id)
            deadline = time.time() + 2.0
            while time.time() < deadline:
                stored = self.repository.get_dataset_version(version.id)
                if stored is not None and stored.status == "invalid":
                    break
                time.sleep(0.05)
        finally:
            dispatcher.shutdown()

        stored = self.repository.get_dataset_version(version.id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "invalid")
        self.assertEqual(stored.issues[0].code, "profile_runtime_error")


def _profile() -> DatasetProfile:
    return DatasetProfile(
        format="csv",
        sheets=[
            DatasetSheetProfile(
                name="__root__",
                row_count=1,
                columns=[
                    DatasetColumnProfile(
                        name="date",
                        inferred_type="string",
                        null_ratio=0.0,
                        unique_count=1,
                        examples=["2026-07-01"],
                    )
                ],
            )
        ],
    )
