"""Dataset profiling for exemplar execution."""

from __future__ import annotations

import json
import csv
import io
import os
from zipfile import BadZipFile
from typing import Any

import pandas as pd
import xxhash
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from application.datasets.jobs import DatasetProfileJobResult
from application.datasets.models import (
    DatasetIssue as AppDatasetIssue,
    DatasetProfile as AppDatasetProfile,
    DatasetVersion as AppDatasetVersion,
)
from application.datasets.repository import RawFileStorage
from agent.runtime.contracts import DatasetFileProfile, DatasetProfile, FieldProfile
from agent.runtime.dataset_registry import REGISTRY, resolve_paths

CSV_DELIMITERS = [",", ";", "\t", "|"]
CSV_ENCODINGS = [
    ("utf-8-sig", None),
    ("utf-8", None),
    ("cp1251", "CSV encoding cp1251 was detected"),
]


def _checksum_file(path: str) -> str:
    hasher = xxhash.xxh64()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _logical_type(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "number"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    return "string"


def _sample_values(series: pd.Series, limit: int = 3) -> list[str]:
    values: list[str] = []
    for value in series.dropna().head(limit).tolist():
        values.append(str(value))
    return values


def _profile_dataframe(
    dataset_id: str,
    logical_name: str,
    path: str,
    df: pd.DataFrame,
    sheet_names: list[str] | None = None,
) -> DatasetFileProfile:
    columns: list[FieldProfile] = []
    for column_name in df.columns:
        series = df[column_name]
        columns.append(
            FieldProfile(
                name=str(column_name),
                logical_type=_logical_type(series),
                null_ratio=float(series.isna().mean()) if len(df) else 0.0,
                unique_count=int(series.nunique(dropna=True)),
                sample_values=_sample_values(series),
            )
        )

    warnings: list[str] = []
    if df.empty:
        warnings.append("dataset is empty")

    return DatasetFileProfile(
        dataset_id=dataset_id,
        logical_name=logical_name,
        path=path,
        format=os.path.splitext(path)[1].lstrip(".").lower(),
        sheet_names=sheet_names or [],
        row_count=int(len(df)),
        checksum=_checksum_file(path),
        columns=columns,
        warnings=warnings,
    )


def _read_json_df(path: str) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as fh:
        payload: Any = json.load(fh)
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    if isinstance(payload, dict):
        return pd.DataFrame([payload])
    return pd.DataFrame()


def _profile_path(dataset_id: str, logical_name: str, path: str) -> DatasetFileProfile | None:
    if not os.path.exists(path):
        return None

    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        with pd.ExcelFile(path) as excel:
            sheet_names = list(excel.sheet_names)
            df = pd.read_excel(excel, sheet_name=sheet_names[0] if sheet_names else 0)
        return _profile_dataframe(dataset_id, logical_name, path, df, sheet_names=sheet_names)
    if ext == ".json":
        df = _read_json_df(path)
        return _profile_dataframe(dataset_id, logical_name, path, df)

    raise ValueError(f"Unsupported dataset format: {path}")


def profile_dataset(project_root: str, dataset_id: str) -> DatasetProfile:
    entry = REGISTRY[dataset_id]
    files: list[DatasetFileProfile] = []
    warnings: list[str] = []
    for path in resolve_paths(project_root, dataset_id):
        profile = _profile_path(entry.dataset_id, entry.logical_name, path)
        if profile is None:
            warnings.append(f"missing file: {path}")
            continue
        files.append(profile)
    return DatasetProfile(
        dataset_id=entry.dataset_id,
        logical_name=entry.logical_name,
        files=files,
        warnings=warnings,
    )


def profile_datasets(project_root: str, dataset_ids: list[str]) -> list[DatasetProfile]:
    return [profile_dataset(project_root, dataset_id) for dataset_id in dataset_ids]


def profile_dataset_version(
    version: AppDatasetVersion,
    storage: RawFileStorage,
) -> DatasetProfileJobResult:
    if not version.storage_key or not version.format:
        return _invalid_result(
            version.id,
            "profile_metadata_missing",
            "Dataset version is missing storage metadata for profiling",
        )

    try:
        with storage.open_read(version.storage_key) as stream:
            if version.format == "csv":
                profile = _profile_uploaded_csv(stream)
            elif version.format == "json":
                profile = _profile_uploaded_json(stream)
            elif version.format == "xlsx":
                profile = _profile_uploaded_xlsx(stream)
            else:
                return _invalid_result(
                    version.id,
                    "unsupported_format",
                    f"Unsupported dataset format: {version.format}",
                )
    except FileNotFoundError:
        return _invalid_result(
            version.id,
            "storage_missing",
            "Stored dataset file is missing",
        )
    except UnicodeDecodeError:
        return _invalid_result(
            version.id,
            "csv_encoding_unsupported",
            "CSV encoding is unsupported",
        )
    except json.JSONDecodeError:
        return _invalid_result(
            version.id,
            "json_invalid",
            "JSON payload could not be parsed",
        )
    except ValueError as exc:
        issue_code = {
            "csv": "csv_invalid",
            "json": "json_invalid",
            "xlsx": "xlsx_invalid",
        }.get(version.format, "profile_invalid")
        return _invalid_result(version.id, issue_code, str(exc))
    except Exception:
        return _invalid_result(
            version.id,
            "profile_runtime_error",
            "Dataset profiling failed unexpectedly",
        )

    return DatasetProfileJobResult(
        version_id=version.id,
        profile=profile,
        issues=[],
        success=True,
    )


def _profile_uploaded_csv(stream) -> AppDatasetProfile:
    warnings: list[str] = []
    sample_bytes = stream.read(4096)
    stream.seek(0)
    chosen_encoding = None
    sample_text = None

    for encoding, warning in CSV_ENCODINGS:
        try:
            sample_text = sample_bytes.decode(encoding)
            chosen_encoding = encoding
            if warning:
                warnings.append(warning)
            break
        except UnicodeDecodeError:
            continue

    if chosen_encoding is None or sample_text is None:
        raise UnicodeDecodeError("csv", sample_bytes, 0, len(sample_bytes), "unsupported encoding")

    delimiter = ","
    if sample_text.strip():
        try:
            dialect = csv.Sniffer().sniff(sample_text, delimiters="".join(CSV_DELIMITERS))
            delimiter = dialect.delimiter
            if delimiter != ",":
                warnings.append(f"CSV delimiter '{delimiter}' was detected")
        except csv.Error:
            warnings.append("CSV delimiter detection fell back to comma")

    stream.seek(0)
    try:
        text_stream = io.TextIOWrapper(stream, encoding=chosen_encoding, newline="")
        reader = csv.reader(text_stream, delimiter=delimiter)
        header = None
        row_count = 0

        for row in reader:
            if not any(_has_value(cell) for cell in row):
                continue
            if header is None:
                header = _normalize_header(row, warnings)
                continue
            row_count += 1
    except UnicodeDecodeError as exc:
        raise exc
    finally:
        try:
            text_stream.detach()
        except Exception:
            pass

    if header is None:
        warnings.append("CSV file is empty")
        header = []

    return AppDatasetProfile(
        format="csv",
        row_count=row_count,
        columns=header,
        warnings=warnings,
    )


def _profile_uploaded_json(stream) -> AppDatasetProfile:
    warnings: list[str] = []
    payload = json.load(io.TextIOWrapper(stream, encoding="utf-8-sig"))

    if isinstance(payload, dict):
        columns = [str(key) for key in payload.keys()]
        row_count = 1
    elif isinstance(payload, list):
        if not payload:
            columns = []
            row_count = 0
            warnings.append("JSON array is empty")
        else:
            object_items = [item for item in payload if isinstance(item, dict)]
            if not object_items:
                raise ValueError("JSON payload does not contain object rows")

            columns = []
            seen_columns: set[str] = set()
            for item in object_items:
                for key in item.keys():
                    key_name = str(key)
                    if key_name not in seen_columns:
                        seen_columns.add(key_name)
                        columns.append(key_name)

            row_count = len(payload)
            if len(object_items) != len(payload):
                warnings.append("JSON contains non-object rows")
    else:
        raise ValueError("JSON payload must be an object or a list of objects")

    return AppDatasetProfile(
        format="json",
        row_count=row_count,
        columns=columns,
        warnings=warnings,
    )


def _profile_uploaded_xlsx(stream) -> AppDatasetProfile:
    warnings: list[str] = []
    try:
        workbook = load_workbook(stream, read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise ValueError("Workbook is invalid") from exc

    sheet_names = list(workbook.sheetnames)
    primary_columns: list[str] = []
    row_count = 0
    non_empty_sheets = 0

    try:
        for worksheet in workbook.worksheets:
            header = None
            sheet_row_count = 0
            for row in worksheet.iter_rows(values_only=True):
                values = list(row)
                if not any(_has_value(cell) for cell in values):
                    continue
                if header is None:
                    header = _normalize_header(values, warnings)
                    continue
                sheet_row_count += 1

            if header is None:
                warnings.append(f"Worksheet '{worksheet.title}' is empty")
                continue

            non_empty_sheets += 1
            if not primary_columns:
                primary_columns = header
            row_count += sheet_row_count

        if non_empty_sheets == 0:
            warnings.append("Workbook contains no populated worksheets")
    finally:
        workbook.close()

    return AppDatasetProfile(
        format="xlsx",
        row_count=row_count,
        columns=primary_columns,
        sheet_names=sheet_names,
        warnings=warnings,
    )


def _normalize_header(values: list[Any], warnings: list[str]) -> list[str]:
    header: list[str] = []
    for index, value in enumerate(values, start=1):
        if _has_value(value):
            header.append(str(value).strip())
        else:
            header.append(f"column_{index}")
            warnings.append(f"Header column {index} was blank and was renamed")
    return header


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _invalid_result(version_id: str, code: str, message: str) -> DatasetProfileJobResult:
    return DatasetProfileJobResult(
        version_id=version_id,
        profile=None,
        issues=[AppDatasetIssue(code=code, message=message, severity="error")],
        success=False,
    )
