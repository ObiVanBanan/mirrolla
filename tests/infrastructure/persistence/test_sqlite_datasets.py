from __future__ import annotations

import tempfile
import unittest
import sqlite3

from application.datasets.models import AnalysisDatasetSelection, DatasetIssue, DatasetProfile
from application.datasets.service import DatasetService
from infrastructure.persistence.sqlite_datasets import (
    ImmutableDatasetError,
    ImmutableDatasetVersionError,
    InvalidDatasetVersionPurgeError,
    ReferencedDatasetVersionError,
    SqliteDatasetRepository,
)


class NoopDispatcher:
    def dispatch_profile(self, version_id: str) -> None:
        return None


class SqliteDatasetRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = f"{self.tmpdir.name}/datasets.sqlite"
        self.repository = SqliteDatasetRepository(self.db_path)
        self.service = DatasetService(self.repository, NoopDispatcher())

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_restart_repository_preserves_records(self) -> None:
        workspace = self.service.ensure_default_workspace()
        dataset, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
            display_name="Sales",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )

        restarted = SqliteDatasetRepository(self.db_path)
        loaded_workspace = restarted.get_workspace(workspace.id)
        loaded_dataset = restarted.get_dataset(dataset.id)
        loaded_version = restarted.get_dataset_version(version.id)

        self.assertIsNotNone(loaded_workspace)
        self.assertIsNotNone(loaded_dataset)
        self.assertIsNotNone(loaded_version)
        assert loaded_version is not None
        self.assertEqual(loaded_version.storage_key, "workspace/.blobs/blob-a")
        self.assertEqual(loaded_version.checksum_sha256, "sum-a")

    def test_ensure_default_workspace_is_idempotent_across_restarts(self) -> None:
        first = self.service.ensure_default_workspace()

        restarted = SqliteDatasetRepository(self.db_path)
        service = DatasetService(restarted, NoopDispatcher())
        second = service.ensure_default_workspace()

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.name, second.name)

    def test_purge_rejects_referenced_active_version(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )
        self.service.start_profiling(version.id)
        self.service.complete_profile(
            version.id,
            profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
            issues=[DatasetIssue(code="warn", message="warning", severity="warning")],
            success=True,
        )
        self.service.attach_versions_to_analysis("analysis-1", [version.id])

        with self.assertRaises(InvalidDatasetVersionPurgeError):
            self.repository.purge_dataset_version(version.id)

        self.assertIsNotNone(self.repository.get_dataset_version(version.id))

    def test_list_versions_excludes_deleted_by_default(self) -> None:
        workspace = self.service.ensure_default_workspace()
        dataset, first = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales-1.csv",
        )
        _, second = self.service.register_upload_receiving(
            workspace.id,
            dataset_id=dataset.id,
            original_filename="sales-2.csv",
        )

        for version, checksum in ((first, "sum-a"), (second, "sum-b")):
            self.service.complete_upload(
                version.id,
                storage_key=f"workspace/.blobs/{checksum}",
                size_bytes=10,
                checksum_sha256=checksum,
                file_format="csv",
            )
            self.service.start_profiling(version.id)
            self.service.complete_profile(
                version.id,
                profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
                issues=[],
                success=True,
            )

        self.service.soft_delete_version(first.id)
        listed = self.repository.list_dataset_versions(dataset.id)

        self.assertEqual([item.id for item in listed], [second.id])
        self.assertIsNotNone(self.repository.get_dataset_version(first.id))

    def test_count_versions_by_storage_key_counts_soft_deleted_versions(self) -> None:
        workspace = self.service.ensure_default_workspace()
        dataset, first = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales-1.csv",
        )
        _, second = self.service.register_upload_receiving(
            workspace.id,
            dataset_id=dataset.id,
            original_filename="sales-2.csv",
        )

        for version in (first, second):
            self.service.complete_upload(
                version.id,
                storage_key="workspace/.blobs/shared",
                size_bytes=10,
                checksum_sha256=f"sum-{version.id}",
                file_format="csv",
            )

        self.service.soft_delete_version(first.id)

        self.assertEqual(
            self.repository.count_versions_by_storage_key("workspace/.blobs/shared"),
            2,
        )

    def test_cannot_replace_storage_metadata_after_upload(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        uploaded = self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )

        with self.assertRaises(ImmutableDatasetVersionError):
            self.repository.save_dataset_version(
                uploaded.model_copy(update={"storage_key": "workspace/.blobs/blob-b"})
            )

    def test_cannot_move_dataset_between_workspaces(self) -> None:
        first = self.service.ensure_default_workspace()
        second = self.repository.save_workspace(
            first.model_copy(update={"id": "workspace-2", "name": "Workspace 2"})
        )
        dataset = self.service.create_dataset(first.id, "Sales")

        with self.assertRaises(ImmutableDatasetError):
            self.repository.save_dataset(
                dataset.model_copy(update={"workspace_id": second.id})
            )

    def test_purge_rejects_ready_unreferenced_version(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )

        with self.assertRaises(InvalidDatasetVersionPurgeError):
            self.repository.purge_dataset_version(version.id)

    def test_purge_allows_deleted_unreferenced_version(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )
        self.service.soft_delete_version(version.id)

        deleted = self.repository.purge_dataset_version(version.id)

        self.assertTrue(deleted)
        self.assertIsNone(self.repository.get_dataset_version(version.id))

    def test_purge_rejects_deleted_referenced_version(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, version = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales.csv",
        )
        self.service.complete_upload(
            version.id,
            storage_key="workspace/.blobs/blob-a",
            size_bytes=10,
            checksum_sha256="sum-a",
            file_format="csv",
        )
        self.service.start_profiling(version.id)
        self.service.complete_profile(
            version.id,
            profile=DatasetProfile(format="csv", row_count=10, columns=["date"]),
            issues=[],
            success=True,
        )
        self.service.attach_versions_to_analysis("analysis-1", [version.id])
        self.service.soft_delete_version(version.id)

        with self.assertRaises(ReferencedDatasetVersionError):
            self.repository.purge_dataset_version(version.id)

    def test_save_analysis_dataset_selections_rejects_other_analysis_id(self) -> None:
        with self.assertRaises(ValueError):
            self.repository.save_analysis_dataset_selections(
                "analysis-a",
                [
                    AnalysisDatasetSelection(
                        analysis_id="analysis-b",
                        dataset_version_id="version-1",
                        position=0,
                    )
                ],
            )

    def test_save_analysis_dataset_selections_accepts_generator_and_preserves_order(self) -> None:
        workspace = self.service.ensure_default_workspace()
        _, first = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales-1.csv",
        )
        _, second = self.service.register_upload_receiving(
            workspace.id,
            original_filename="sales-2.csv",
        )
        items = (
            AnalysisDatasetSelection(
                analysis_id="analysis-1",
                dataset_version_id=version_id,
                position=index,
            )
            for index, version_id in enumerate([second.id, first.id])
        )

        saved = self.repository.save_analysis_dataset_selections("analysis-1", items)

        self.assertEqual([item.dataset_version_id for item in saved], [second.id, first.id])
        loaded = self.repository.list_analysis_dataset_selections("analysis-1")
        self.assertEqual([item.dataset_version_id for item in loaded], [second.id, first.id])

    def test_repository_migrates_existing_schema(self) -> None:
        db_path = f"{self.tmpdir.name}/legacy.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            PRAGMA user_version = 1;
            CREATE TABLE workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE datasets (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE dataset_versions (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                storage_key TEXT,
                format TEXT,
                size_bytes INTEGER,
                checksum_sha256 TEXT,
                status TEXT NOT NULL,
                profile_json TEXT,
                issues_json TEXT,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            );
            CREATE TABLE analysis_datasets (
                analysis_id TEXT NOT NULL,
                dataset_version_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (analysis_id, dataset_version_id)
            );
            """
        )
        conn.commit()
        conn.close()

        migrated = SqliteDatasetRepository(db_path)
        with migrated._connection() as check_conn:
            user_version = check_conn.execute("PRAGMA user_version").fetchone()[0]
            indexes = check_conn.execute(
                "PRAGMA index_list('analysis_datasets')"
            ).fetchall()

        self.assertEqual(user_version, SqliteDatasetRepository.SCHEMA_VERSION)
        self.assertTrue(any("sqlite_autoindex_analysis_datasets_2" in row[1] for row in indexes))
