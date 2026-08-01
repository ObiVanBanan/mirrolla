"""
Pydantic models shared across router, planner, and executor.
"""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class SkillType(str, Enum):
    SALES_DECLINE = "sales-decline-analysis"
    INVENTORY = "inventory-planning"
    PORTFOLIO_GROWTH = "portfolio-growth"
    REVIEWS_PRICING = "reviews-and-pricing"


class AnalysisMode(str, Enum):
    GENERAL = "general"
    SPECIALIZED = "specialized"


class Question(BaseModel):
    text: str = Field(..., description="Manager question in Russian")


class RoutingResult(BaseModel):
    analysis_mode: AnalysisMode | None = Field(
        default=None,
        description="General or specialized analysis mode",
    )
    skill: SkillType | None = Field(
        default=None,
        description="Selected analytical skill when specialized analysis is required",
    )
    skill_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence for the selected skill",
    )
    product_codes: list[str] = Field(
        default_factory=list,
        description="Product codes found in the question",
    )
    period_days: int = Field(
        default=14,
        ge=1,
        le=365,
        description="Analysis period in days",
    )

    @model_validator(mode="before")
    @classmethod
    def _infer_analysis_mode(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("analysis_mode") is None:
            data["analysis_mode"] = (
                AnalysisMode.SPECIALIZED if data.get("skill") is not None else AnalysisMode.GENERAL
            )
        return data

    @model_validator(mode="after")
    def _validate_skill_consistency(self):
        if self.analysis_mode == AnalysisMode.GENERAL and self.skill is not None:
            raise ValueError("General analysis must not specify a skill")
        if self.analysis_mode == AnalysisMode.SPECIALIZED and self.skill is None:
            raise ValueError("Specialized analysis must specify a skill")
        return self


class PeriodSpec(BaseModel):
    current_days: int = Field(
        ...,
        ge=1,
        le=365,
        description="Length of the current analysis period in days",
    )
    comparison: str = Field(
        default="previous_equal_period",
        description="Comparison strategy",
    )


class Hypothesis(BaseModel):
    id: str = Field(..., description="Hypothesis identifier: H1, H2, ...")
    title: str = Field(..., description="Short hypothesis title")
    datasets: list[str] = Field(
        ...,
        description="Datasets required to validate the hypothesis",
    )
    method: str = Field(..., description="Validation method")
    helpers: list[str] = Field(
        default_factory=list,
        description="Helper function names from helpers/",
    )


class AnalysisPlan(BaseModel):
    analysis_mode: AnalysisMode | None = Field(
        default=None,
        description="General or specialized analysis mode",
    )
    skill: SkillType | None = Field(
        default=None,
        description="Analytical skill when specialized analysis is required",
    )
    question: str = Field(..., description="Original manager question")
    product_codes: list[str] = Field(
        default_factory=list,
        description="Product codes for the analysis",
    )
    period: PeriodSpec = Field(..., description="Analysis period")
    hypotheses: list[Hypothesis] = Field(
        ...,
        description="Hypotheses to validate",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known data limitations",
    )

    @model_validator(mode="before")
    @classmethod
    def _infer_analysis_mode(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("analysis_mode") is None:
            data["analysis_mode"] = (
                AnalysisMode.SPECIALIZED if data.get("skill") is not None else AnalysisMode.GENERAL
            )
        return data

    @model_validator(mode="after")
    def _validate_skill_consistency(self):
        if self.analysis_mode == AnalysisMode.GENERAL and self.skill is not None:
            raise ValueError("General analysis plan must not specify a skill")
        if self.analysis_mode == AnalysisMode.SPECIALIZED and self.skill is None:
            raise ValueError("Specialized analysis plan must specify a skill")
        return self


class HypothesisResult(BaseModel):
    hypothesis_id: str = Field(..., description="Hypothesis identifier")
    title: str = Field(..., description="Hypothesis title")
    confirmed: bool | None = Field(
        None,
        description="True if confirmed, False if rejected, None if inconclusive",
    )
    detail: str = Field(..., description="Validation details")
    data: dict | None = Field(
        None,
        description="Structured metrics used by the validation",
    )


class Finding(BaseModel):
    entity_type: str = Field(..., description="product, review, category, ...")
    entity_id: str = Field(..., description="Stable entity identifier")
    name: str = Field(..., description="Human-readable entity name")
    priority: str = Field(
        "medium",
        description="critical, high, medium, or low",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Concrete reasons with numbers when available",
    )
    metrics: dict = Field(
        default_factory=dict,
        description="Computed metrics for the finding",
    )
    recommended_action: str = Field(
        "",
        description="Concrete manager action",
    )


class ExecutionDatasetMetadata(BaseModel):
    dataset_id: str = Field(..., description="Dataset identifier")
    dataset_version_id: str = Field(..., description="Exact dataset version identifier")
    original_filename: str = Field(..., description="Uploaded filename")
    format: str = Field(..., description="Dataset format")
    checksum_sha256: str = Field(..., description="Blob checksum")


class ExecutionMetadata(BaseModel):
    manifest_version: str = Field(..., description="Execution manifest schema version")
    analysis_id: str | None = Field(default=None, description="Analysis identifier")
    datasets: list[ExecutionDatasetMetadata] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    question: str = Field(..., description="Original manager question")
    analysis_mode: AnalysisMode | None = Field(
        default=None,
        description="General or specialized analysis mode",
    )
    skill: SkillType | None = Field(
        default=None,
        description="Selected analytical skill",
    )
    answer_status: str = Field(
        "answered",
        description="answered, partial, or not_enough_data",
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="Concrete findings returned to the manager",
    )
    hypothesis_results: list[HypothesisResult] = Field(
        default_factory=list,
        description="Optional per-hypothesis results",
    )
    charts: list[str] = Field(
        default_factory=list,
        description="Downloaded chart paths",
    )
    summary: str = Field(
        "",
        description="Human-readable final answer",
    )
    answer: str = Field(
        "",
        description="Direct answer returned to the user",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Limitations of the analysis",
    )
    code_generated: str | None = Field(
        None,
        description="Generated Python code when available",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Execution errors",
    )
    execution_metadata: ExecutionMetadata | None = Field(
        default=None,
        description="Resolved dataset provenance for the execution",
    )

    @model_validator(mode="before")
    @classmethod
    def _infer_analysis_mode(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("analysis_mode") is None:
            data["analysis_mode"] = (
                AnalysisMode.SPECIALIZED if data.get("skill") is not None else AnalysisMode.GENERAL
            )
        return data

    @model_validator(mode="after")
    def _validate_skill_consistency(self):
        if self.analysis_mode == AnalysisMode.GENERAL and self.skill is not None:
            raise ValueError("General execution result must not specify a skill")
        if self.analysis_mode == AnalysisMode.SPECIALIZED and self.skill is None:
            raise ValueError("Specialized execution result must specify a skill")
        if not self.answer and self.summary:
            self.answer = self.summary
        if self.analysis_mode == AnalysisMode.GENERAL and not (self.answer or self.summary):
            raise ValueError("General execution result must include an answer or summary")
        return self
