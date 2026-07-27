from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from application.datasets.models import DatasetIssue, DatasetProfile


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
