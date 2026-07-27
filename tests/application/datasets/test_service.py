from __future__ import annotations

import unittest
from collections.abc import Iterable

from pydantic import ValidationError

from application.datasets.jobs import DatasetProfileJobResult
from application.datasets.models import (
    AnalysisDatasetSelection,
    Dataset,
    DatasetIssue,
    DatasetProfile,
    DataWorkspace,
    DatasetVersion,
)
from application.datasets.service import (
    DEFAULT_WORKSPACE_ID,
    DatasetService,
    InvalidDatasetStateError,
)


class InMemoryDatasetRepository:
    def __init__(self) -> None:
        self.workspaces: dict[str, DataWorkspace] = {}
        self.datasets: dict[str, Dataset] = {}
        self.versions: dict[str, DatasetVersion] = {}
        self.analysis_selections: dict[str, list[AnalysisDatasetSelection]] = {}

    def get_workspace(self, workspace_id: str) -> DataWorkspace | None:
        return self.workspaces.get(workspace_id)

    def get_workspace_by_name(self, name: str) -> DataWorkspace | None:
        return next((item for item in self.workspaces.values() if item.name == name), None)

    def save_workspace(self, workspace: DataWorkspace) -> DataWorkspace:
        self.workspaces[workspace.id] = workspace
        return workspace

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        return self.datasets.get(dataset_id)

    def save_dataset(self, dataset: Dataset) -> Dataset:
        self.datasets[dataset.id] = dataset
        return dataset

    def list_datasets(self, workspace_id: str) -> list[Dataset]:
        return [item for item in self.datasets.values() if item.workspace_id == workspace_id]

    def get_dataset_version(self, version_id: str) -> DatasetVersion | None:
        return self.versions.get(version_id)

    def save_dataset_version(self, version: DatasetVersion) -> DatasetVersion:
        self.versions[version.id] = version
        return version

    def list_dataset_versions(self, dataset_id: str) -> list[DatasetVersion]:
        return [item for item in self.versions.values() if item.dataset_id == dataset_id]

    def find_dataset_version_by_checksum(
        self,
        workspace_id: str,
        checksum_sha256: str,
    ) -> DatasetVersion | None:
        for version in self.versions.values():
            dataset = self.datasets.get(version.dataset_id)
            if dataset and dataset.workspace_id == workspace_id and version.checksum_sha256 == checksum_sha256:
                return version
        return None

    def save_analysis_dataset_selections(
        self,
        analysis_id: str,
        selections: Iterable[AnalysisDatasetSelection],
    ) -> list[AnalysisDatasetSelection]:
        values = list(selections)
        self.analysis_selections[analysis_id] = values
        return values

    def list_analysis_dataset_selections(
        self,
        analysis_id: str,
    ) -> list[AnalysisDatasetSelection]:
        return list(self.analysis_selections.get(analysis_id, []))

    def is_version_referenced(self, version_id: str) -> bool:
        return any(
            selection.dataset_version_id == version_id
            for selections in self.analysis_selections.values()
            for selection in selections
        )


class RecordingDispatcher:
    def __init__(self) -> None:
        self.version_ids: list[str] = []

    def dispatch_profile(self, version_id: str) -> None:
        self.version_ids.append(version_id)


class FailingDispatcher:
    def dispatch_profile(self, version_id: str) -> None:
        raise RuntimeError(f"dispatcher failed for {version_id}")


class DatasetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryDatasetRepository()
        self.dispatcher = RecordingDispatcher()
        self.service = DatasetService(self.repository, self.dispatcher)

    def test_dataset_version_status_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValidationError):
            DatasetVersion(
                id="dsv_1",
                dataset_id="ds_1",
                original_filename="sales.csv",
                status="broken",
                created_at=self.service._utcnow(),
            )

    def test_storage_key_is_metadata_not_filename_alias(self) -> None:
        version = DatasetVersion(
            id="dsv_1",
            dataset_id="ds_1",
            original_filename="../../sales.csv",
            storage_key="workspace/default/dsv_1/raw/blob-001",
            format="CSV",
            status="uploaded",
            created_at=self.service._utcnow(),
        )

        self.assertEqual(version.original_filename, "../../sales.csv")
        self.assertEqual(version.storage_key, "workspace/default/dsv_1/raw/blob-001")
        self.assertNotEqual(version.original_filename, version.storage_key)
        self.assertEqual(version.format, "csv")

    def test_default_workspace_is_idempotent(self) -> None:
        first = self.service.ensure_default_workspace()
        second = self.service.ensure_default_workspace()

        self.assertEqual(first.id, DEFAULT_WORKSPACE_ID)
        self.assertEqual(second.id, first.id)
        self.assertEqual(len(self.repository.workspaces), 1)

    def test_upload_lifecycle_uses_in_memory_fakes(self) -> None:
        workspace = self.service.ensure_default_workspace()
        dataset, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="ozon_may.xlsx",
            display_name="Продажи Ozon",
        )

        self.assertEqual(dataset.workspace_id, workspace.id)
        self.assertEqual(version.status, "receiving")
        self.assertIsNone(version.storage_key)

        uploaded = self.service.complete_upload(
            version.id,
            storage_key="uploads/default/sales/raw/blob-001",
            size_bytes=128,
            checksum_sha256="abc123",
            file_format="XLSX",
        )
        self.assertEqual(uploaded.status, "uploaded")
        self.assertEqual(uploaded.storage_key, "uploads/default/sales/raw/blob-001")
        self.assertEqual(uploaded.format, "xlsx")

        profiling = self.service.start_profiling(version.id)
        self.assertEqual(profiling.status, "profiling")
        self.assertEqual(self.dispatcher.version_ids, [version.id])

        ready = self.service.complete_profile(
            version.id,
            profile=DatasetProfile(
                format="xlsx",
                row_count=42,
                columns=["date", "product_code", "sales"],
                sheet_names=["Sheet1"],
            ),
            issues=[],
            success=True,
        )
        self.assertEqual(ready.status, "ready")
        self.assertIsNotNone(ready.profile)
        self.assertEqual(ready.profile.columns, ["date", "product_code", "sales"])

    def test_complete_profile_rejects_ready_without_profile(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="blob-1",
            size_bytes=10,
            checksum_sha256="sum-1",
            file_format="csv",
        )
        self.service.start_profiling(version.id)

        with self.assertRaises(InvalidDatasetStateError):
            self.service.complete_profile(
                version.id,
                profile=None,
                issues=[],
                success=True,
            )

    def test_complete_profile_rejects_ready_with_error_issue(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="blob-1",
            size_bytes=10,
            checksum_sha256="sum-1",
            file_format="csv",
        )
        self.service.start_profiling(version.id)

        with self.assertRaises(InvalidDatasetStateError):
            self.service.complete_profile(
                version.id,
                profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
                issues=[DatasetIssue(code="bad_schema", message="schema mismatch", severity="error")],
                success=True,
            )

    def test_attach_versions_deduplicates_and_preserves_order(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, first = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        _, second = self.service.register_upload_receiving(
            workspace.id,
            original_filename="stocks.csv",
        )
        self.service.complete_upload(
            first.id,
            storage_key="blob-1",
            size_bytes=10,
            checksum_sha256="sum-1",
            file_format="csv",
        )
        self.service.complete_upload(
            second.id,
            storage_key="blob-2",
            size_bytes=10,
            checksum_sha256="sum-2",
            file_format="csv",
        )
        self.service.start_profiling(first.id)
        self.service.start_profiling(second.id)
        self.service.complete_profile(
            first.id,
            profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
            success=True,
        )
        self.service.complete_profile(
            second.id,
            profile=DatasetProfile(format="csv", row_count=8, columns=["sku"]),
            success=True,
        )

        selections = self.service.attach_versions_to_analysis(
            "analysis-1",
            [second.id, first.id, second.id],
        )

        self.assertEqual(
            [item.dataset_version_id for item in selections],
            [second.id, first.id],
        )
        self.assertEqual([item.position for item in selections], [0, 1])

    def test_attach_rejects_non_ready_version(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )

        with self.assertRaises(InvalidDatasetStateError):
            self.service.attach_versions_to_analysis("analysis-1", [version.id])

    def test_soft_delete_allows_referenced_version_and_preserves_existing_analysis(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="blob-1",
            size_bytes=10,
            checksum_sha256="sum-1",
            file_format="csv",
        )
        self.service.start_profiling(version.id)
        self.service.complete_profile(
            version.id,
            profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
            issues=[DatasetIssue(code="sample_warning", message="warning", severity="warning")],
            success=True,
        )
        self.service.attach_versions_to_analysis("analysis-1", [version.id])

        deleted = self.service.soft_delete_version(version.id)
        self.assertEqual(deleted.status, "deleted")
        self.assertIsNotNone(deleted.deleted_at)
        self.assertEqual(
            [item.dataset_version_id for item in self.repository.list_analysis_dataset_selections("analysis-1")],
            [version.id],
        )

        with self.assertRaises(InvalidDatasetStateError):
            self.service.attach_versions_to_analysis("analysis-2", [version.id])

    def test_start_profiling_rolls_back_if_dispatch_fails(self) -> None:
        self.service = DatasetService(self.repository, FailingDispatcher())
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="blob-1",
            size_bytes=10,
            checksum_sha256="sum-1",
            file_format="csv",
        )

        with self.assertRaises(RuntimeError):
            self.service.start_profiling(version.id)

        stored = self.repository.get_dataset_version(version.id)
        assert stored is not None
        self.assertEqual(stored.status, "uploaded")

    def test_job_result_rejects_inconsistent_success(self) -> None:
        with self.assertRaises(ValidationError):
            DatasetProfileJobResult(
                version_id="dsv_1",
                profile=None,
                issues=[],
                success=True,
            )
