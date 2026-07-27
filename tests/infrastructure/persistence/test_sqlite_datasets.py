from __future__ import annotations

import tempfile
import unittest

from application.datasets.models import DatasetIssue, DatasetProfile
from application.datasets.service import DatasetService
from infrastructure.persistence.sqlite_datasets import (
    ReferencedDatasetVersionError,
    SqliteDatasetRepository,
)


class NoopDispatcher:
    def dispatch_profile(self, version_id: str) -> None:
        return None


class SqliteDatasetRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = f"{self.tmpdir.name}/datasets.sqlite"
        self.repository = SqliteDatasetRepository(self.db_path)
        self.service = DatasetService(self.repository, NoopDispatcher())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_restart_repository_preserves_records(self) -> None:
        workspace = self.service.ensure_default_workspace()
        dataset, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
            display_name="Sales",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )

        restarted = SqliteDatasetRepository(self.db_path)
        loaded_workspace = restarted.get_workspace(workspace.id)
        loaded_dataset = restarted.get_dataset(dataset.id)
        loaded_version = restarted.get_dataset_version(version.id)

        self.assertIsNotNone(loaded_workspace)
        self.assertIsNotNone(loaded_dataset)
        self.assertIsNotNone(loaded_version)
        assert loaded_version is not None
        self.assertEqual(loaded_version.storage_key, "workspace/.blobs/blob-a")
        self.assertEqual(loaded_version.checksum_sha256, "sum-a")

    def test_ensure_default_workspace_is_idempotent_across_restarts(self) -> None:
        first = self.service.ensure_default_workspace()

        restarted = SqliteDatasetRepository(self.db_path)
        service = DatasetService(restarted, NoopDispatcher())
        second = service.ensure_default_workspace()

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.name, second.name)

    def test_purge_rejects_referenced_version(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )
        self.service.start_profiling(version.id)
        self.service.complete_profile(
            version.id,
            profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
            issues=[DatasetIssue(code="warn", message="warning", severity="warning")],
            success=True,
        )
        self.service.attach_versions_to_analysis("analysis-1", [version.id])

        with self.assertRaises(ReferencedDatasetVersionError):
            self.repository.purge_dataset_version(version.id)

        self.assertIsNotNone(self.repository.get_dataset_version(version.id))

    def test_list_versions_excludes_deleted_by_default(self) -> None:
        workspace = self.service.ensure_default_workspace()
        dataset, first = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales-1.csv",
        )
        _, second = self.service.register_upload_receiving(
            workspace.id,
            dataset_id=dataset.id,
            original_filename="sales-2.csv",
        )

        for version, checksum in ((first, "sum-a"), (second, "sum-b")):
            self.service.complete_upload(
                version.id,
                storage_key=f"workspace/.blobs/{checksum}",
                size_bytes=10,
                checksum_sha256=checksum,
                file_format="csv",
            )
            self.service.start_profiling(version.id)
            self.service.complete_profile(
                version.id,
                profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
                issues=[],
                success=True,
            )

        self.service.soft_delete_version(first.id)
        listed = self.repository.list_dataset_versions(dataset.id)

        self.assertEqual([item.id for item in listed], [second.id])
        self.assertIsNotNone(self.repository.get_dataset_version(first.id))

    def test_count_versions_by_storage_key_counts_soft_deleted_versions(self) -> None:
        workspace = self.service.ensure_default_workspace()
        dataset, first = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales-1.csv",
        )
        _, second = self.service.register_upload_receiving(
            workspace.id,
            dataset_id=dataset.id,
            original_filename="sales-2.csv",
        )

        for version in (first, second):
            self.service.complete_upload(
                version.id,
                storage_key="workspace/.blobs/shared",
                size_bytes=10,
                checksum_sha256=f"sum-{version.id}",
                file_format="csv",
            )

        self.service.soft_delete_version(first.id)

        self.assertEqual(
            self.repository.count_versions_by_storage_key("workspace/.blobs/shared"),
            2,
        )
