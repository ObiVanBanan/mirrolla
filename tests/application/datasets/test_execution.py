from __future__ import annotations

import unittest

from application.datasets.execution import (
    DatasetExecutionResolver,
    DatasetProfileMissingError,
    DatasetVersionNotExecutableError,
)
from application.datasets.models import DatasetIssue
from application.datasets.service import DatasetService
from tests.application.datasets.test_service import InMemoryDatasetRepository, RecordingDispatcher, _profile


class DatasetExecutionResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryDatasetRepository()
        self.service = DatasetService(self.repository, RecordingDispatcher())
        self.workspace = self.service.ensure_default_workspace()
        self.resolver = DatasetExecutionResolver(self.repository)

    def _create_ready_version(self, filename: str, checksum: str):
        dataset, version = self.service.register_upload_receiving(
            self.workspace.id,
            original_filename=filename,
        )
        self.service.complete_upload(
            version.id,
            storage_key=f"default/.blobs/{checksum}",
            size_bytes=10,
            checksum_sha256=checksum,
            file_format=filename.rsplit(".", 1)[-1],
        )
        self.service.start_profiling(version.id)
        ready = self.service.complete_profile(
            version.id,
            profile=_profile(filename.rsplit(".", 1)[-1], "__root__", ["date", "sales"], row_count=10),
            success=True,
        )
        return dataset, ready

    def test_resolve_for_analysis_preserves_position(self) -> None:
        _, first = self._create_ready_version("sales.csv", "sum-1")
        _, second = self._create_ready_version("stocks.csv", "sum-2")
        self.service.attach_versions_to_analysis("analysis-1", [second.id, first.id])

        resolved = self.resolver.resolve_for_analysis("analysis-1")

        self.assertEqual([item.dataset_version_id for item in resolved], [second.id, first.id])
        self.assertEqual([item.position for item in resolved], [0, 1])

    def test_soft_deleted_version_remains_executable_for_existing_analysis(self) -> None:
        _, version = self._create_ready_version("sales.csv", "sum-1")
        self.service.attach_versions_to_analysis("analysis-1", [version.id])
        self.service.soft_delete_version(version.id)

        resolved = self.resolver.resolve_for_analysis("analysis-1")

        self.assertEqual(resolved[0].status, "deleted")

    def test_new_analysis_rejects_deleted_version(self) -> None:
        _, version = self._create_ready_version("sales.csv", "sum-1")
        self.service.soft_delete_version(version.id)

        with self.assertRaises(DatasetVersionNotExecutableError):
            self.resolver.resolve_version_ids([version.id])

    def test_resolve_rejects_versions_with_error_issues(self) -> None:
        _, version = self._create_ready_version("sales.csv", "sum-1")
        stored = self.repository.get_dataset_version(version.id)
        assert stored is not None
        stored.issues = [DatasetIssue(code="bad_schema", message="broken", severity="error")]
        self.repository.save_dataset_version(stored)
        self.service.attach_versions_to_analysis("analysis-1", [version.id])

        with self.assertRaises(DatasetVersionNotExecutableError):
            self.resolver.resolve_for_analysis("analysis-1")

    def test_resolve_rejects_missing_profile(self) -> None:
        _, version = self.service.register_upload_receiving(
            self.workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="default/.blobs/sum-1",
            size_bytes=10,
            checksum_sha256="sum-1",
            file_format="csv",
        )
        stored = self.repository.get_dataset_version(version.id)
        assert stored is not None
        stored.status = "ready"
        self.repository.save_dataset_version(stored)
        self.service.attach_versions_to_analysis("analysis-1", [version.id])

        with self.assertRaises(DatasetProfileMissingError):
            self.resolver.resolve_for_analysis("analysis-1")

    def test_resolve_version_ids_rejects_cross_workspace_selection(self) -> None:
        other_workspace = self.repository.save_workspace(
            self.workspace.model_copy(update={"id": "other", "name": "Other"})
        )
        _, first = self._create_ready_version("sales.csv", "sum-1")
        dataset, version = self.service.register_upload_receiving(
            other_workspace.id,
            original_filename="stocks.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="other/.blobs/sum-2",
            size_bytes=10,
            checksum_sha256="sum-2",
            file_format="csv",
        )
        self.service.start_profiling(version.id)
        second = self.service.complete_profile(
            version.id,
            profile=_profile("csv", "__root__", ["sku", "stock"], row_count=10),
            success=True,
        )

        with self.assertRaises(DatasetVersionNotExecutableError):
            self.resolver.resolve_version_ids([first.id, second.id])
