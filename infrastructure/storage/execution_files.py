from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, Field

from application.datasets.execution import (
    DatasetBlobMissingError,
    DatasetExecutionError,
)
from application.datasets.repository import RawFileStorage


class DatasetChecksumMismatchError(DatasetExecutionError):
    code = "dataset_checksum_mismatch"
    message = "Attached dataset checksum does not match stored blob"


class MaterializedDatasetFile(BaseModel):
    dataset_version_id: str
    sandbox_filename: str
    local_path: str
    checksum_sha256: str


class MaterializedDatasetBundle(BaseModel):
    files: list[MaterializedDatasetFile] = Field(default_factory=list)


@contextmanager
def materialize_execution_files(
    inputs: Sequence,
    storage: RawFileStorage,
) -> Iterator[MaterializedDatasetBundle]:
    temp_dir = Path(tempfile.mkdtemp(prefix="mirrolla-exec-"))
    try:
        files: list[MaterializedDatasetFile] = []
        for index, item in enumerate(inputs, start=1):
            suffix = f".{item.format.lower().lstrip('.')}" if item.format else ""
            sandbox_filename = f"dataset_{index:03d}{suffix}"
            target_path = temp_dir / sandbox_filename
            checksum = hashlib.sha256()

            try:
                source_stream = storage.open_read(item.storage_key)
            except FileNotFoundError as exc:
                raise DatasetBlobMissingError(
                    f"Blob is missing for dataset version {item.dataset_version_id}"
                ) from exc

            with source_stream, target_path.open("wb") as target:
                while True:
                    chunk = source_stream.read(64 * 1024)
                    if not chunk:
                        break
                    checksum.update(chunk)
                    target.write(chunk)

            actual_checksum = checksum.hexdigest()
            if actual_checksum != item.checksum_sha256:
                raise DatasetChecksumMismatchError(
                    f"Checksum mismatch for dataset version {item.dataset_version_id}"
                )

            files.append(
                MaterializedDatasetFile(
                    dataset_version_id=item.dataset_version_id,
                    sandbox_filename=sandbox_filename,
                    local_path=str(target_path),
                    checksum_sha256=actual_checksum,
                )
            )

        yield MaterializedDatasetBundle(files=files)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
