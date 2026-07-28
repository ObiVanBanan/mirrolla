"""Versioned runtime contracts for exemplar execution."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FieldProfile(BaseModel):
    name: str
    logical_type: str
    null_ratio: float = Field(ge=0.0, le=1.0)
    unique_count: int = Field(ge=0)
    sample_values: list[str] = Field(default_factory=list)


class DatasetFileProfile(BaseModel):
    dataset_id: str
    logical_name: str
    path: str
    format: str
    sheet_names: list[str] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    checksum: str
    columns: list[FieldProfile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    dataset_id: str
    logical_name: str
    files: list[DatasetFileProfile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SemanticFieldBinding(BaseModel):
    concept: str
    dataset_id: str
    column_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    required: bool = False
    reason: str = ""


class SkillMetadata(BaseModel):
    skill_id: str
    version: str
    required_concepts: list[str] = Field(default_factory=list)
    optional_concepts: list[str] = Field(default_factory=list)
    output_contract_version: str
    validator_id: str
    reference_helpers: list[str] = Field(default_factory=list)


class ExecutionManifest(BaseModel):
    question: str
    skill_id: str
    skill_version: str
    plan_version: str
    product_codes: list[str] = Field(default_factory=list)
    current_period_days: int
    comparison_method: str
    datasets: list[DatasetProfile] = Field(default_factory=list)
    semantic_bindings: list[SemanticFieldBinding] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    expected_output_contract: str
    runtime_restrictions: list[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    code: str
    message: str


class ValidationReport(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

