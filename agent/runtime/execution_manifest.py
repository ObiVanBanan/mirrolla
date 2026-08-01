from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from agent.schemas import AnalysisMode
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
    analysis_mode: AnalysisMode | None = None
    skill_id: str | None = None
    datasets: list[ExecutionDatasetReference] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _infer_analysis_mode(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("analysis_mode") is None:
            data["analysis_mode"] = (
                AnalysisMode.SPECIALIZED if data.get("skill_id") else AnalysisMode.GENERAL
            )
        return data


class AttachedExecutionInput(BaseModel):
    analysis_id: str
    manifest: ExecutionManifest
    files: list[MaterializedDatasetFile] = Field(default_factory=list)
