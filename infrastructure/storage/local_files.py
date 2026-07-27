from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from application.datasets.repository import StoredObject


ALLOWED_EXTENSIONS = frozenset({".xlsx", ".csv", ".json"})
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]")


class LocalFileStorageError(Exception):
    """Base local storage error."""


class InvalidFilenameError(LocalFileStorageError):
    """Original filename is invalid or unsafe."""


class UnsupportedExtensionError(LocalFileStorageError):
    """Original filename uses unsupported extension."""


class FileTooLargeError(LocalFileStorageError):
    """Upload exceeds byte limit."""


class EmptyFileError(LocalFileStorageError):
    """Upload stream is empty."""


class StreamReadError(LocalFileStorageError):
    """Upload stream failed during read."""


class LocalRawFileStorage:
    def __init__(
        self,
        root_dir: str | Path,
        *,
        chunk_size: int = 64 * 1024,
        allowed_extensions: set[str] | frozenset[str] = ALLOWED_EXTENSIONS,
    ) -> None:
        self._root_dir = Path(root_dir).resolve()
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        self._chunk_size = chunk_size
        self._allowed_extensions = {ext.lower() for ext in allowed_extensions}
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def put_stream(
        self,
        *,
        workspace_id: str,
        dataset_id: str,
        version_id: str,
        original_filename: str,
        stream,
        max_bytes: int,
    ) -> StoredObject:
        self._validate_original_filename(original_filename)
        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")

        temp_dir = self._version_temp_dir(workspace_id, dataset_id, version_id)
        temp_dir.mkdir(parents=True, exist_ok=True)

        temp_name = f"{uuid4().hex}.part"
        temp_path = temp_dir / temp_name
        total_size = 0
        checksum = hashlib.sha256()
        blob_path: Path | None = None

        try:
            with temp_path.open("xb") as handle:
                while True:
                    try:
                        chunk = stream.read(self._chunk_size)
                    except Exception as exc:
                        raise StreamReadError("Failed to read upload stream") from exc

                    if not chunk:
                        break

                    if not isinstance(chunk, (bytes, bytearray)):
                        raise StreamReadError("Upload stream must return bytes")

                    total_size += len(chunk)
                    if total_size > max_bytes:
                        raise FileTooLargeError(f"Upload exceeds {max_bytes} bytes")

                    checksum.update(chunk)
                    handle.write(chunk)

            if total_size == 0:
                raise EmptyFileError("Upload stream is empty")

            checksum_sha256 = checksum.hexdigest()
            blob_path = self._blob_path(workspace_id, checksum_sha256)
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            deduplicated = self._commit_blob(temp_path, blob_path)
            storage_key = self._storage_key_for(blob_path)
            return StoredObject(
                storage_key=storage_key,
                size_bytes=total_size,
                checksum_sha256=checksum_sha256,
                deduplicated=deduplicated,
            )
        except Exception:
            if blob_path is not None and blob_path.exists():
                # Keep already committed shared blobs; only temp artifacts are cleaned here.
                pass
            temp_path.unlink(missing_ok=True)
            raise

    def open_read(self, storage_key: str):
        path = self._resolve_storage_key(storage_key)
        return path.open("rb")

    def delete(self, storage_key: str) -> None:
        # Caller must prove no remaining metadata references the storage object.
        path = self._resolve_storage_key(storage_key)
        path.unlink(missing_ok=True)

    def _validate_original_filename(self, original_filename: str) -> str:
        if not original_filename or original_filename.strip() == "":
            raise InvalidFilenameError("Original filename must be present")

        candidate = original_filename.strip()
        candidate_path = Path(candidate)
        if candidate_path.name != candidate:
            raise InvalidFilenameError("Original filename must not contain path segments")
        if CONTROL_CHARS_RE.search(candidate):
            raise InvalidFilenameError("Original filename contains control characters")
        if candidate.startswith(("/", "\\")):
            raise InvalidFilenameError("Original filename must not be absolute")
        if re.match(r"^[a-zA-Z]:[\\/]", candidate):
            raise InvalidFilenameError("Original filename must not be an absolute Windows path")

        suffix = candidate_path.suffix.lower()
        if suffix not in self._allowed_extensions:
            raise UnsupportedExtensionError(f"Unsupported extension: {suffix or '<none>'}")

        return suffix

    def _version_temp_dir(self, workspace_id: str, dataset_id: str, version_id: str) -> Path:
        return self._safe_join(self._root_dir, workspace_id, dataset_id, version_id, "tmp")

    def _blob_path(self, workspace_id: str, checksum_sha256: str) -> Path:
        return self._safe_join(self._root_dir, workspace_id, ".blobs", checksum_sha256)

    def _commit_blob(self, temp_path: Path, blob_path: Path) -> bool:
        try:
            os.link(temp_path, blob_path)
            temp_path.unlink(missing_ok=True)
            return False
        except FileExistsError:
            temp_path.unlink(missing_ok=True)
            return True

    def _storage_key_for(self, path: Path) -> str:
        return path.relative_to(self._root_dir).as_posix()

    def _resolve_storage_key(self, storage_key: str) -> Path:
        path = self._safe_join(self._root_dir, *storage_key.split("/"))
        if not path.exists():
            raise FileNotFoundError(storage_key)
        return path

    @staticmethod
    def _safe_join(base: Path, *parts: str) -> Path:
        path = base.joinpath(*parts).resolve()
        if path != base and base not in path.parents:
            raise InvalidFilenameError("Resolved path escapes storage root")
        return path
