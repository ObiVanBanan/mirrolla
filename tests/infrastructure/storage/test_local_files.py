from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from infrastructure.storage.local_files import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFilenameError,
    LocalRawFileStorage,
    StreamReadError,
    UnsupportedExtensionError,
)


class ChunkTrackingStream:
    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError("Storage must read in chunks, not all at once")
        return self._stream.read(size)


class ExplodingStream:
    def __init__(self, payload: bytes, fail_after_reads: int) -> None:
        self._stream = io.BytesIO(payload)
        self._remaining_reads = fail_after_reads

    def read(self, size: int = -1) -> bytes:
        if self._remaining_reads == 0:
            raise OSError("stream failed")
        self._remaining_reads -= 1
        return self._stream.read(size)


class LocalRawFileStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.storage = LocalRawFileStorage(self.root, chunk_size=4)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def put_stream(
        self,
        payload: bytes,
        *,
        original_filename: str = "sales.csv",
        workspace_id: str = "workspace-1",
        dataset_id: str = "dataset-1",
        version_id: str = "version-1",
        max_bytes: int = 1024,
        stream=None,
    ):
        input_stream = stream or io.BytesIO(payload)
        return self.storage.put_stream(
            workspace_id=workspace_id,
            dataset_id=dataset_id,
            version_id=version_id,
            original_filename=original_filename,
            stream=input_stream,
            max_bytes=max_bytes,
        )

    def test_put_stream_writes_chunked_and_returns_checksum(self) -> None:
        payload = b"hello world"
        stream = ChunkTrackingStream(payload)

        stored = self.put_stream(payload, stream=stream)

        self.assertGreater(len(stream.read_sizes), 1)
        self.assertTrue(all(size == 4 for size in stream.read_sizes[:-1]))
        with self.storage.open_read(stored.storage_key) as handle:
            self.assertEqual(handle.read(), payload)
        self.assertEqual(stored.size_bytes, len(payload))
        self.assertEqual(stored.checksum_sha256, hashlib.sha256(payload).hexdigest())

    def test_rejects_non_positive_chunk_size(self) -> None:
        with self.assertRaises(ValueError):
            LocalRawFileStorage(self.root, chunk_size=0)

        with self.assertRaises(ValueError):
            LocalRawFileStorage(self.root, chunk_size=-1)

    def test_rejects_non_positive_max_bytes(self) -> None:
        with self.assertRaises(ValueError):
            self.put_stream(b"data", max_bytes=0)

        with self.assertRaises(ValueError):
            self.put_stream(b"data", max_bytes=-1)

    def test_rejects_path_traversal_filename(self) -> None:
        with self.assertRaises(InvalidFilenameError):
            self.put_stream(b"data", original_filename="../../secret.csv")

    def test_rejects_absolute_windows_path(self) -> None:
        with self.assertRaises(InvalidFilenameError):
            self.put_stream(b"data", original_filename="C:\\secret.csv")

    def test_rejects_absolute_unix_path(self) -> None:
        with self.assertRaises(InvalidFilenameError):
            self.put_stream(b"data", original_filename="/secret.csv")

    def test_rejects_unsupported_extension(self) -> None:
        with self.assertRaises(UnsupportedExtensionError):
            self.put_stream(b"data", original_filename="sales.xls")

    def test_rejects_empty_file(self) -> None:
        with self.assertRaises(EmptyFileError):
            self.put_stream(b"", original_filename="sales.csv")

    def test_rejects_oversize_and_cleans_partials(self) -> None:
        with self.assertRaises(FileTooLargeError):
            self.put_stream(b"abcdef", max_bytes=4)

        self.assertEqual(list(self.root.rglob("*.part")), [])

    def test_cleans_partial_file_if_stream_raises(self) -> None:
        stream = ExplodingStream(b"abcdef", fail_after_reads=1)

        with self.assertRaises(StreamReadError):
            self.put_stream(b"", stream=stream)

        self.assertEqual(list(self.root.rglob("*.part")), [])

    def test_deduplicates_same_content_inside_workspace(self) -> None:
        first = self.put_stream(
            b"same-content",
            version_id="version-1",
            original_filename="sales.csv",
        )
        second = self.put_stream(
            b"same-content",
            version_id="version-2",
            original_filename="sales.csv",
        )

        self.assertFalse(first.deduplicated)
        self.assertTrue(second.deduplicated)
        self.assertEqual(first.storage_key, second.storage_key)
        self.assertEqual(len(list(self.root.rglob(".blobs/*"))), 1)

    def test_same_content_in_different_workspace_creates_separate_blob(self) -> None:
        first = self.put_stream(b"same-content", workspace_id="workspace-1")
        second = self.put_stream(b"same-content", workspace_id="workspace-2")

        self.assertNotEqual(first.storage_key, second.storage_key)
        self.assertEqual(len(list(self.root.rglob(".blobs/*"))), 2)

    def test_delete_then_reupload_same_content_creates_new_blob(self) -> None:
        first = self.put_stream(b"same-content")

        self.storage.delete(first.storage_key)
        second = self.put_stream(b"same-content", version_id="version-2")

        self.assertFalse(second.deduplicated)
        self.assertEqual(first.storage_key, second.storage_key)
        with self.storage.open_read(second.storage_key) as handle:
            self.assertEqual(handle.read(), b"same-content")

    def test_cleans_temp_file_if_commit_fails(self) -> None:
        with patch.object(self.storage, "_commit_blob", side_effect=OSError("commit failed")):
            with self.assertRaises(OSError):
                self.put_stream(b"payload")

        self.assertEqual(list(self.root.rglob("*.part")), [])
        self.assertEqual(list(self.root.rglob(".blobs/*")), [])
