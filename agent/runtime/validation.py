"""Deterministic validation for exemplar results."""

from __future__ import annotations

import math

from agent.runtime.contracts import ExecutionManifest, ValidationIssue, ValidationReport


def validate_generic_result(parsed: dict, manifest: ExecutionManifest) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if not parsed:
        issues.append(ValidationIssue(code="missing_json", message="Result JSON is missing"))
        return ValidationReport(valid=False, issues=issues)

    answer_status = parsed.get("answer_status")
    if answer_status not in {"answered", "partial", "not_enough_data"}:
        issues.append(ValidationIssue(code="invalid_status", message="answer_status must be answered, partial or not_enough_data"))

    if not parsed.get("answer"):
        issues.append(ValidationIssue(code="missing_answer", message="Field answer is required"))

    findings = parsed.get("findings", [])
    if answer_status == "answered" and not findings:
        issues.append(ValidationIssue(code="empty_findings", message="answered result must include findings"))

    for index, finding in enumerate(findings):
        if not finding.get("entity_id"):
            issues.append(ValidationIssue(code="missing_entity_id", message=f"findings[{index}] is missing entity_id"))
        if not finding.get("reasons"):
            issues.append(ValidationIssue(code="missing_reasons", message=f"findings[{index}] is missing reasons"))
        for metric_name, metric_value in (finding.get("metrics") or {}).items():
            if isinstance(metric_value, float) and (math.isnan(metric_value) or math.isinf(metric_value)):
                issues.append(ValidationIssue(code="invalid_metric", message=f"findings[{index}].metrics[{metric_name}] contains NaN or inf"))

    return ValidationReport(valid=not issues, issues=issues)


def validate_sales_decline_result(parsed: dict, manifest: ExecutionManifest) -> ValidationReport:
    issues: list[ValidationIssue] = []
    findings = parsed.get("findings", [])
    if len(findings) > 20:
        issues.append(ValidationIssue(code="too_many_findings", message="sales-decline result must return at most 20 findings"))

    requested_products = set(manifest.product_codes)
    for index, finding in enumerate(findings):
        metrics = finding.get("metrics") or {}
        if "change_pct" not in metrics:
            issues.append(ValidationIssue(code="missing_change_pct", message=f"findings[{index}] is missing metrics.change_pct"))
        if requested_products and finding.get("entity_id") not in requested_products:
            issues.append(ValidationIssue(code="unexpected_product", message=f"findings[{index}] entity_id is outside requested product codes"))

    return ValidationReport(valid=not issues, issues=issues)

