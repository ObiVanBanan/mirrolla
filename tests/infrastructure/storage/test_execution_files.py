from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from application.datasets.execution import DatasetBlobMissingError, ResolvedDatasetInput
from application.datasets.models import DatasetProfile, DatasetSheetProfile
from infrastructure.storage.execution_files import (
    DatasetChecksumMismatchError,
    materialize_execution_files,
)
from infrastructure.storage.local_files import LocalRawFileStorage


class MaterializeExecutionFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage = LocalRawFileStorage(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _store(self, payload: bytes, version_id: str):
        return self.storage.put_stream(
            workspace_id="default",
            dataset_id="dataset-1",
            version_id=version_id,
            original_filename="sales.csv",
            stream=io.BytesIO(payload),
            max_bytes=1024,
        )

    def _input(self, version_id: str, stored, filename: str = "sales.csv") -> ResolvedDatasetInput:
        return ResolvedDatasetInput(
            position=0,
            dataset_id="dataset-1",
            dataset_version_id=version_id,
            display_name="Sales",
            original_filename=filename,
            format="csv",
            checksum_sha256=stored.checksum_sha256,
            storage_key=stored.storage_key,
            profile=DatasetProfile(
                format="csv",
                sheets=[DatasetSheetProfile(name="__root__", row_count=1, columns=[])],
            ),
            status="ready",
        )

    def test_materializes_unique_ascii_filenames_and_cleans_up_on_success(self) -> None:
        first = self._store(b"date,sales\n2026-07-01,10\n", "version-1")
        second = self._store(b"date,sales\n2026-07-02,11\n", "version-2")
        inputs = [
            self._input("version-1", first, "report.csv"),
            self._input("version-2", second, "report.csv"),
        ]
        bundle_path = None

        with materialize_execution_files(inputs, self.storage) as bundle:
            self.assertEqual(
                [item.sandbox_filename for item in bundle.files],
                ["dataset_001.csv", "dataset_002.csv"],
            )
            self.assertTrue(all(Path(item.local_path).exists() for item in bundle.files))
            bundle_path = Path(bundle.files[0].local_path).parent

        assert bundle_path is not None
        self.assertFalse(bundle_path.exists())

    def test_checksum_mismatch_raises_and_cleans_temp_dir(self) -> None:
        stored = self._store(b"date,sales\n2026-07-01,10\n", "version-1")
        bad_input = self._input("version-1", stored)
        bad_input.checksum_sha256 = "0" * 64
        tmp_before = set(Path(tempfile.gettempdir()).iterdir())

        with self.assertRaises(DatasetChecksumMismatchError):
            with materialize_execution_files([bad_input], self.storage):
                pass

        tmp_after = set(Path(tempfile.gettempdir()).iterdir())
        self.assertEqual(tmp_before, tmp_after)

    def test_missing_blob_raises_before_ci(self) -> None:
        stored = self._store(b"date,sales\n2026-07-01,10\n", "version-1")
        self.storage.delete(stored.storage_key)
        missing_input = self._input("version-1", stored)

        with self.assertRaises(DatasetBlobMissingError):
            with materialize_execution_files([missing_input], self.storage):
                pass
