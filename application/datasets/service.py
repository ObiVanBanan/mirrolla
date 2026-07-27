from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from application.datasets.models import (
    AnalysisDatasetSelection,
    Dataset,
    DatasetIssue,
    DatasetProfile,
    DataWorkspace,
    DatasetVersion,
    DatasetVersionStatus,
)
from application.datasets.repository import DatasetJobDispatcher, DatasetRepository


DEFAULT_WORKSPACE_ID = "default"
DEFAULT_WORKSPACE_NAME = "Default workspace"

ALLOWED_STATUS_TRANSITIONS: dict[DatasetVersionStatus, set[DatasetVersionStatus]] = {
    "receiving": {"uploaded", "deleted"},
    "uploaded": {"profiling", "deleted"},
    "profiling": {"ready", "invalid", "deleted"},
    "ready": {"deleted"},
    "invalid": {"deleted"},
    "deleted": set(),
}


class DatasetServiceError(Exception):
    """Base dataset service error."""


class DatasetNotFoundError(DatasetServiceError):
    """Dataset was not found."""


class DatasetVersionNotFoundError(DatasetServiceError):
    """Dataset version was not found."""


class WorkspaceNotFoundError(DatasetServiceError):
    """Workspace was not found."""


class InvalidDatasetStateError(DatasetServiceError):
    """Requested state transition or action is invalid."""


class DatasetService:
    def __init__(
        self,
        repository: DatasetRepository,
        job_dispatcher: DatasetJobDispatcher,
    ) -> None:
        self._repository = repository
        self._job_dispatcher = job_dispatcher

    def ensure_default_workspace(self) -> DataWorkspace:
        workspace = self._repository.get_workspace(DEFAULT_WORKSPACE_ID)
        if workspace is not None:
            return workspace

        existing = self._repository.get_workspace_by_name(DEFAULT_WORKSPACE_NAME)
        if existing is not None:
            return existing

        workspace = DataWorkspace(
            id=DEFAULT_WORKSPACE_ID,
            name=DEFAULT_WORKSPACE_NAME,
            created_at=self._utcnow(),
        )
        return self._repository.save_workspace(workspace)

    def create_dataset(
        self,
        workspace_id: str,
        display_name: str,
        *,
        source_type: str = "upload",
    ) -> Dataset:
        self._require_workspace(workspace_id)
        dataset = Dataset(
            id=self._new_id("ds"),
            workspace_id=workspace_id,
            display_name=display_name,
            source_type=source_type,
            created_at=self._utcnow(),
        )
        return self._repository.save_dataset(dataset)

    def register_upload_receiving(
        self,
        workspace_id: str,
        *,
        original_filename: str,
        display_name: str | None = None,
        dataset_id: str | None = None,
        source_type: str = "upload",
    ) -> tuple[Dataset, DatasetVersion]:
        self._require_workspace(workspace_id)

        if dataset_id is None:
            dataset = self.create_dataset(
                workspace_id,
                display_name=display_name or original_filename,
                source_type=source_type,
            )
        else:
            dataset = self._require_dataset(dataset_id)
            if dataset.workspace_id != workspace_id:
                raise InvalidDatasetStateError("Dataset belongs to another workspace")

        version = DatasetVersion(
            id=self._new_id("dsv"),
            dataset_id=dataset.id,
            original_filename=original_filename,
            status="receiving",
            created_at=self._utcnow(),
        )
        saved = self._repository.save_dataset_version(version)
        return dataset, saved

    def complete_upload(
        self,
        version_id: str,
        *,
        storage_key: str,
        size_bytes: int,
        checksum_sha256: str,
        file_format: str,
    ) -> DatasetVersion:
        version = self._require_version(version_id)
        self._transition(version, "uploaded")
        version.storage_key = storage_key
        version.size_bytes = size_bytes
        version.checksum_sha256 = checksum_sha256
        version.format = file_format.strip().lower()
        saved = self._repository.save_dataset_version(version)
        return saved

    def start_profiling(self, version_id: str) -> DatasetVersion:
        version = self._require_version(version_id)
        self._transition(version, "profiling")
        saved = self._repository.save_dataset_version(version)
        self._job_dispatcher.dispatch_profile(version_id)
        return saved

    def complete_profile(
        self,
        version_id: str,
        *,
        profile: DatasetProfile | None,
        issues: Sequence[DatasetIssue] | None = None,
        success: bool,
    ) -> DatasetVersion:
        version = self._require_version(version_id)
        target_status: DatasetVersionStatus = "ready" if success else "invalid"
        self._transition(version, target_status)
        version.profile = profile
        version.issues = list(issues or [])
        saved = self._repository.save_dataset_version(version)
        return saved

    def soft_delete_version(self, version_id: str) -> DatasetVersion:
        version = self._require_version(version_id)
        if self._repository.is_version_referenced(version_id):
            raise InvalidDatasetStateError("Referenced dataset version cannot be deleted")
        self._transition(version, "deleted")
        version.deleted_at = self._utcnow()
        return self._repository.save_dataset_version(version)

    def attach_versions_to_analysis(
        self,
        analysis_id: str,
        dataset_version_ids: Sequence[str],
    ) -> list[AnalysisDatasetSelection]:
        unique_ids = self._deduplicate_ids(dataset_version_ids)
        if not unique_ids:
            return self._repository.save_analysis_dataset_selections(analysis_id, [])

        selections: list[AnalysisDatasetSelection] = []
        workspace_id: str | None = None

        for position, version_id in enumerate(unique_ids):
            version = self._require_version(version_id)
            if version.status != "ready":
                raise InvalidDatasetStateError(
                    f"Dataset version {version_id} is not ready for analysis"
                )

            dataset = self._require_dataset(version.dataset_id)
            if workspace_id is None:
                workspace_id = dataset.workspace_id
            elif dataset.workspace_id != workspace_id:
                raise InvalidDatasetStateError("All selected versions must belong to one workspace")

            selections.append(
                AnalysisDatasetSelection(
                    analysis_id=analysis_id,
                    dataset_version_id=version.id,
                    position=position,
                )
            )

        return self._repository.save_analysis_dataset_selections(analysis_id, selections)

    def _require_workspace(self, workspace_id: str) -> DataWorkspace:
        workspace = self._repository.get_workspace(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"Workspace {workspace_id} was not found")
        return workspace

    def _require_dataset(self, dataset_id: str) -> Dataset:
        dataset = self._repository.get_dataset(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} was not found")
        return dataset

    def _require_version(self, version_id: str) -> DatasetVersion:
        version = self._repository.get_dataset_version(version_id)
        if version is None:
            raise DatasetVersionNotFoundError(f"Dataset version {version_id} was not found")
        return version

    def _transition(
        self,
        version: DatasetVersion,
        target_status: DatasetVersionStatus,
    ) -> None:
        allowed = ALLOWED_STATUS_TRANSITIONS[version.status]
        if target_status not in allowed:
            raise InvalidDatasetStateError(
                f"Cannot transition dataset version from {version.status} to {target_status}"
            )
        version.status = target_status

    @staticmethod
    def _deduplicate_ids(values: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                ordered.append(value)
        return ordered

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)
