from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from application.datasets.models import DatasetProfile, DatasetVersionStatus
from application.datasets.repository import DatasetRepository


EXECUTABLE_ANALYSIS_STATUSES = frozenset({"ready", "deleted"})
NEW_ANALYSIS_ALLOWED_STATUSES = frozenset({"ready"})


class DatasetExecutionError(Exception):
    code = "dataset_execution_error"
    message = "Dataset execution failed"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.detail = message or self.message


class DatasetSelectionMissingError(DatasetExecutionError):
    code = "dataset_selection_missing"
    message = "Attached dataset selection is missing"


class DatasetVersionNotExecutableError(DatasetExecutionError):
    code = "dataset_version_not_executable"
    message = "Attached dataset version is not executable"


class DatasetProfileMissingError(DatasetExecutionError):
    code = "dataset_profile_missing"
    message = "Attached dataset profile is missing"


class DatasetBlobMissingError(DatasetExecutionError):
    code = "dataset_blob_missing"
    message = "Attached dataset blob is missing"


class ResolvedDatasetInput(BaseModel):
    position: int = Field(ge=0)
    dataset_id: str
    dataset_version_id: str
    display_name: str
    original_filename: str
    format: str
    checksum_sha256: str
    storage_key: str
    profile: DatasetProfile
    status: DatasetVersionStatus


class DatasetExecutionResolver:
    def __init__(self, repository: DatasetRepository) -> None:
        self._repository = repository

    def resolve_for_analysis(self, analysis_id: str) -> list[ResolvedDatasetInput]:
        selections = self._repository.list_analysis_dataset_selections(analysis_id)
        if not selections:
            return []

        return self._resolve_selections(selections)

    def resolve_version_ids(
        self,
        dataset_version_ids: Sequence[str],
    ) -> list[ResolvedDatasetInput]:
        if not dataset_version_ids:
            return []

        seen: set[str] = set()
        ordered_ids: list[str] = []
        for version_id in dataset_version_ids:
            if version_id not in seen:
                seen.add(version_id)
                ordered_ids.append(version_id)

        return self._resolve_selections(
            [
                type("Selection", (), {
                    "analysis_id": "__pending__",
                    "dataset_version_id": version_id,
                    "position": position,
                })()
                for position, version_id in enumerate(ordered_ids)
            ],
            allowed_statuses=NEW_ANALYSIS_ALLOWED_STATUSES,
        )

    def _resolve_selections(
        self,
        selections,
        *,
        allowed_statuses: frozenset[str] = EXECUTABLE_ANALYSIS_STATUSES,
    ) -> list[ResolvedDatasetInput]:
        resolved: list[ResolvedDatasetInput] = []
        for selection in sorted(selections, key=lambda item: item.position):
            version = self._repository.get_dataset_version(selection.dataset_version_id)
            if version is None:
                raise DatasetSelectionMissingError(
                    f"Dataset version {selection.dataset_version_id} was not found"
                )

            dataset = self._repository.get_dataset(version.dataset_id)
            if dataset is None:
                raise DatasetSelectionMissingError(
                    f"Dataset {version.dataset_id} was not found for version {version.id}"
                )

            if version.status not in allowed_statuses:
                raise DatasetVersionNotExecutableError(
                    f"Dataset version {version.id} is in status {version.status}"
                )
            if not version.storage_key or not version.format or not version.checksum_sha256:
                raise DatasetVersionNotExecutableError(
                    f"Dataset version {version.id} is missing storage metadata"
                )
            if version.profile is None:
                raise DatasetProfileMissingError(
                    f"Dataset version {version.id} does not have a profile"
                )
            if any(issue.severity == "error" for issue in version.issues):
                raise DatasetVersionNotExecutableError(
                    f"Dataset version {version.id} has profile errors"
                )

            resolved.append(
                ResolvedDatasetInput(
                    position=selection.position,
                    dataset_id=dataset.id,
                    dataset_version_id=version.id,
                    display_name=dataset.display_name,
                    original_filename=version.original_filename,
                    format=version.format,
                    checksum_sha256=version.checksum_sha256,
                    storage_key=version.storage_key,
                    profile=version.profile,
                    status=version.status,
                )
            )

        return resolved
