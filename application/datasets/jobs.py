from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from application.datasets.models import DatasetIssue, DatasetProfile
from application.datasets.repository import DatasetRepository, RawFileStorage
from application.datasets.service import DatasetService, InvalidDatasetStateError


class DatasetProfileJob(BaseModel):
    version_id: str = Field(min_length=1)


class DatasetProfileJobResult(BaseModel):
    version_id: str = Field(min_length=1)
    profile: DatasetProfile | None = None
    issues: list[DatasetIssue] = Field(default_factory=list)
    success: bool

    @model_validator(mode="after")
    def validate_ready_invariant(self) -> "DatasetProfileJobResult":
        has_error_issue = any(issue.severity == "error" for issue in self.issues)
        is_ready = self.profile is not None and not has_error_issue

        if self.success != is_ready:
            raise ValueError(
                "success must match profile readiness: ready requires profile and no error issues"
            )

        return self


class DatasetVersionProfiler(Protocol):
    def __call__(self, version, storage: RawFileStorage) -> DatasetProfileJobResult: ...


class _NoopDatasetJobDispatcher:
    def dispatch_profile(self, version_id: str) -> None:
        return None


def run_dataset_profile_job(
    job: DatasetProfileJob,
    *,
    repository: DatasetRepository,
    storage: RawFileStorage,
    profiler: DatasetVersionProfiler,
):
    version = repository.get_dataset_version(job.version_id)
    if version is None:
        return None

    if version.status in {"ready", "invalid", "deleted"}:
        return version

    if version.status != "profiling":
        raise InvalidDatasetStateError(
            f"Dataset version {job.version_id} must be profiling before job execution"
        )

    result = profiler(version, storage)
    service = DatasetService(repository, _NoopDatasetJobDispatcher())
    return service.complete_profile(
        job.version_id,
        profile=result.profile,
        issues=result.issues,
        success=result.success,
    )
