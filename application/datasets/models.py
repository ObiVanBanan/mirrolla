from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


DatasetVersionStatus = Literal[
    "receiving",
    "uploaded",
    "profiling",
    "ready",
    "invalid",
    "deleted",
]

DatasetSourceType = Literal["upload", "connector", "system"]

DatasetIssueSeverity = Literal["error", "warning"]


class DatasetIssue(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: DatasetIssueSeverity = "error"


class DatasetProfile(BaseModel):
    format: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    columns: list[str] = Field(default_factory=list)
    sheet_names: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("format")
    @classmethod
    def normalize_format(cls, value: str) -> str:
        return value.strip().lower()


class DataWorkspace(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    created_at: datetime


class Dataset(BaseModel):
    id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    source_type: DatasetSourceType = "upload"
    created_at: datetime


class DatasetVersion(BaseModel):
    id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    storage_key: str | None = None
    format: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = None
    status: DatasetVersionStatus
    profile: DatasetProfile | None = None
    issues: list[DatasetIssue] = Field(default_factory=list)
    created_at: datetime
    deleted_at: datetime | None = None

    @field_validator("format")
    @classmethod
    def normalize_optional_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()


class AnalysisDatasetSelection(BaseModel):
    analysis_id: str = Field(min_length=1)
    dataset_version_id: str = Field(min_length=1)
    position: int = Field(ge=0)
