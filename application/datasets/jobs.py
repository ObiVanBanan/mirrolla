from __future__ import annotations

from pydantic import BaseModel, Field

from application.datasets.models import DatasetIssue, DatasetProfile


class DatasetProfileJob(BaseModel):
    version_id: str = Field(min_length=1)


class DatasetProfileJobResult(BaseModel):
    version_id: str = Field(min_length=1)
    profile: DatasetProfile | None = None
    issues: list[DatasetIssue] = Field(default_factory=list)
    success: bool
