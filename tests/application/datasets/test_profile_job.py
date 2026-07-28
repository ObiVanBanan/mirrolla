from __future__ import annotations

import unittest
from collections.abc import Iterable

from application.datasets.jobs import (
    DatasetProfileJob,
    DatasetProfileJobResult,
    run_dataset_profile_job,
)
from application.datasets.models import (
    AnalysisDatasetSelection,
    Dataset,
    DatasetIssue,
    DatasetProfile,
    DataWorkspace,
    DatasetVersion,
)
from application.datasets.service import DatasetService, InvalidDatasetStateError


class InMemoryDatasetRepository:
    def __init__(self) -> None:
        self.workspaces: dict[str, DataWorkspace] = {}
        self.datasets: dict[str, Dataset] = {}
        self.versions: dict[str, DatasetVersion] = {}

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

    def delete_dataset_if_empty(self, dataset_id: str) -> bool:
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return False
        if any(version.dataset_id == dataset_id for version in self.versions.values()):
            return False
        del self.datasets[dataset_id]
        return True

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
        return next(
            (
                version
                for version in self.versions.values()
                if version.checksum_sha256 == checksum_sha256
            ),
            None,
        )

    def count_versions_by_storage_key(self, storage_key: str) -> int:
        return sum(1 for version in self.versions.values() if version.storage_key == storage_key)

    def purge_dataset_version(self, version_id: str) -> bool:
        return self.versions.pop(version_id, None) is not None

    def save_analysis_dataset_selections(
        self,
        analysis_id: str,
        selections: Iterable[AnalysisDatasetSelection],
    ) -> list[AnalysisDatasetSelection]:
        return list(selections)

    def list_analysis_dataset_selections(self, analysis_id: str) -> list[AnalysisDatasetSelection]:
        return []

    def is_version_referenced(self, version_id: str) -> bool:
        return False


class NullDispatcher:
    def dispatch_profile(self, version_id: str) -> None:
        return None


class FakeStorage:
    def open_read(self, storage_key: str):
        raise NotImplementedError

    def put_stream(self, **kwargs):
        raise NotImplementedError

    def delete(self, storage_key: str) -> None:
        return None


class RecordingProfiler:
    def __init__(self, result: DatasetProfileJobResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def __call__(self, version, storage) -> DatasetProfileJobResult:
        self.calls.append(version.id)
        return self.result


class DatasetProfileJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryDatasetRepository()
        self.service = DatasetService(self.repository, NullDispatcher())
        self.workspace = self.service.ensure_default_workspace()
        self.dataset, self.version = self.service.register_upload_receiving(
            self.workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            self.version.id,
            storage_key="default/.blobs/blob",
            size_bytes=4,
            checksum_sha256="sum-1",
            file_format="csv",
        )
        self.service.start_profiling(self.version.id)

    def test_profile_job_marks_version_ready_on_success(self) -> None:
        profiler = RecordingProfiler(
            DatasetProfileJobResult(
                version_id=self.version.id,
                profile=DatasetProfile(format="csv", row_count=1, columns=["date", "sales"]),
                issues=[],
                success=True,
            )
        )

        result = run_dataset_profile_job(
            DatasetProfileJob(version_id=self.version.id),
            repository=self.repository,
            storage=FakeStorage(),
            profiler=profiler,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.profile.columns, ["date", "sales"])
        self.assertEqual(profiler.calls, [self.version.id])

    def test_profile_job_marks_version_invalid_on_failure(self) -> None:
        profiler = RecordingProfiler(
            DatasetProfileJobResult(
                version_id=self.version.id,
                profile=None,
                issues=[DatasetIssue(code="storage_missing", message="missing", severity="error")],
                success=False,
            )
        )

        result = run_dataset_profile_job(
            DatasetProfileJob(version_id=self.version.id),
            repository=self.repository,
            storage=FakeStorage(),
            profiler=profiler,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.issues[0].code, "storage_missing")

    def test_profile_job_is_idempotent_for_ready_version(self) -> None:
        self.service.complete_profile(
            self.version.id,
            profile=DatasetProfile(format="csv", row_count=1, columns=["date"]),
            issues=[],
            success=True,
        )
        profiler = RecordingProfiler(
            DatasetProfileJobResult(
                version_id=self.version.id,
                profile=DatasetProfile(format="csv", row_count=2, columns=["other"]),
                issues=[],
                success=True,
            )
        )

        result = run_dataset_profile_job(
            DatasetProfileJob(version_id=self.version.id),
            repository=self.repository,
            storage=FakeStorage(),
            profiler=profiler,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.profile.columns, ["date"])
        self.assertEqual(profiler.calls, [])

    def test_profile_job_rejects_non_profiling_version(self) -> None:
        second_dataset, second_version = self.service.register_upload_receiving(
            self.workspace.id,
            original_filename="stocks.csv",
        )
        self.service.complete_upload(
            second_version.id,
            storage_key="default/.blobs/blob-2",
            size_bytes=4,
            checksum_sha256="sum-2",
            file_format="csv",
        )
        profiler = RecordingProfiler(
            DatasetProfileJobResult(
                version_id=second_version.id,
                profile=DatasetProfile(format="csv", row_count=1, columns=["sku"]),
                issues=[],
                success=True,
            )
        )

        with self.assertRaises(InvalidDatasetStateError):
            run_dataset_profile_job(
                DatasetProfileJob(version_id=second_version.id),
                repository=self.repository,
                storage=FakeStorage(),
                profiler=profiler,
            )

