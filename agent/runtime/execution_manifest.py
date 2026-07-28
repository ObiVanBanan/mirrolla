from __future__ import annotations

from pydantic import BaseModel, Field

from application.datasets.models import DatasetProfile
from infrastructure.storage.execution_files import MaterializedDatasetFile


class ExecutionDatasetReference(BaseModel):
    position: int = Field(ge=0)
    dataset_id: str
    dataset_version_id: str
    display_name: str
    original_filename: str
    sandbox_filename: str
    format: str
    checksum_sha256: str
    profile: DatasetProfile


class ExecutionManifest(BaseModel):
    manifest_version: str = "1.0"
    analysis_id: str
    question: str
    skill_id: str
    datasets: list[ExecutionDatasetReference] = Field(default_factory=list)


class AttachedExecutionInput(BaseModel):
    analysis_id: str
    manifest: ExecutionManifest
    files: list[MaterializedDatasetFile] = Field(default_factory=list)
