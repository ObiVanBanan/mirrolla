from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from application.datasets.models import (
    AnalysisDatasetSelection,
    Dataset,
    DataWorkspace,
    DatasetVersion,
)


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    size_bytes: int
    checksum_sha256: str
    deduplicated: bool = False


class DatasetRepository(Protocol):
    def get_workspace(self, workspace_id: str) -> DataWorkspace | None: ...
    def get_workspace_by_name(self, name: str) -> DataWorkspace | None: ...
    def save_workspace(self, workspace: DataWorkspace) -> DataWorkspace: ...

    def get_dataset(self, dataset_id: str) -> Dataset | None: ...
    def save_dataset(self, dataset: Dataset) -> Dataset: ...
    def list_datasets(self, workspace_id: str) -> list[Dataset]: ...

    def get_dataset_version(self, version_id: str) -> DatasetVersion | None: ...
    def save_dataset_version(self, version: DatasetVersion) -> DatasetVersion: ...
    def list_dataset_versions(self, dataset_id: str) -> list[DatasetVersion]: ...
    def find_dataset_version_by_checksum(
        self,
        workspace_id: str,
        checksum_sha256: str,
    ) -> DatasetVersion | None: ...

    def save_analysis_dataset_selections(
        self,
        analysis_id: str,
        selections: Iterable[AnalysisDatasetSelection],
    ) -> list[AnalysisDatasetSelection]: ...
    def list_analysis_dataset_selections(
        self,
        analysis_id: str,
    ) -> list[AnalysisDatasetSelection]: ...
    def is_version_referenced(self, version_id: str) -> bool: ...


class RawFileStorage(Protocol):
    def put_stream(
        self,
        *,
        workspace_id: str,
        dataset_id: str,
        version_id: str,
        original_filename: str,
        stream: BinaryIO,
        max_bytes: int,
    ) -> StoredObject: ...
    def open_read(self, storage_key: str) -> BinaryIO: ...
    def delete(self, storage_key: str) -> None: ...


class DatasetJobDispatcher(Protocol):
    def dispatch_profile(self, version_id: str) -> None: ...
