from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from application.datasets.models import (
    AnalysisDatasetSelection,
    Dataset,
    DatasetIssue,
    DatasetProfile,
    DataWorkspace,
    DatasetVersion,
)


class ReferencedDatasetVersionError(Exception):
    """Raised when trying to hard-delete a version used by an analysis."""


class ImmutableDatasetError(Exception):
    """Raised when an immutable dataset field is changed."""


class ImmutableDatasetVersionError(Exception):
    """Raised when an immutable dataset version field is changed."""


class InvalidDatasetVersionPurgeError(Exception):
    """Raised when a dataset version cannot be purged in its current state."""


class SqliteDatasetRepository:
    SCHEMA_VERSION = 2

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get_workspace(self, workspace_id: str) -> DataWorkspace | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, name, created_at FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
        return self._workspace_from_row(row) if row else None

    def get_workspace_by_name(self, name: str) -> DataWorkspace | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, name, created_at FROM workspaces WHERE name = ?",
                (name,),
            ).fetchone()
        return self._workspace_from_row(row) if row else None

    def save_workspace(self, workspace: DataWorkspace) -> DataWorkspace:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (id, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    created_at = excluded.created_at
                """,
                (workspace.id, workspace.name, workspace.created_at.isoformat()),
            )
        return workspace

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, workspace_id, display_name, source_type, created_at
                FROM datasets
                WHERE id = ?
                """,
                (dataset_id,),
            ).fetchone()
        return self._dataset_from_row(row) if row else None

    def save_dataset(self, dataset: Dataset) -> Dataset:
        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT id, workspace_id, display_name, source_type, created_at
                FROM datasets
                WHERE id = ?
                """,
                (dataset.id,),
            ).fetchone()
            if existing is not None:
                self._assert_dataset_immutable(existing, dataset)
            conn.execute(
                """
                INSERT INTO datasets (id, workspace_id, display_name, source_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name
                """,
                (
                    dataset.id,
                    dataset.workspace_id,
                    dataset.display_name,
                    dataset.source_type,
                    dataset.created_at.isoformat(),
                ),
            )
        return dataset

    def list_datasets(self, workspace_id: str) -> list[Dataset]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, display_name, source_type, created_at
                FROM datasets
                WHERE workspace_id = ?
                ORDER BY created_at, id
                """,
                (workspace_id,),
            ).fetchall()
        return [self._dataset_from_row(row) for row in rows]

    def delete_dataset_if_empty(self, dataset_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM datasets
                WHERE id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM dataset_versions
                      WHERE dataset_id = datasets.id
                  )
                """,
                (dataset_id,),
            )
        return cursor.rowcount > 0

    def get_dataset_version(self, version_id: str) -> DatasetVersion | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    dataset_id,
                    original_filename,
                    storage_key,
                    format,
                    size_bytes,
                    checksum_sha256,
                    status,
                    profile_json,
                    issues_json,
                    created_at,
                    deleted_at
                FROM dataset_versions
                WHERE id = ?
                """,
                (version_id,),
            ).fetchone()
        return self._version_from_row(row) if row else None

    def save_dataset_version(self, version: DatasetVersion) -> DatasetVersion:
        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT
                    id,
                    dataset_id,
                    original_filename,
                    storage_key,
                    format,
                    size_bytes,
                    checksum_sha256,
                    status,
                    profile_json,
                    issues_json,
                    created_at,
                    deleted_at
                FROM dataset_versions
                WHERE id = ?
                """,
                (version.id,),
            ).fetchone()
            if existing is not None:
                self._assert_dataset_version_immutable(existing, version)
            conn.execute(
                """
                INSERT INTO dataset_versions (
                    id,
                    dataset_id,
                    original_filename,
                    storage_key,
                    format,
                    size_bytes,
                    checksum_sha256,
                    status,
                    profile_json,
                    issues_json,
                    created_at,
                    deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    storage_key = excluded.storage_key,
                    format = excluded.format,
                    size_bytes = excluded.size_bytes,
                    checksum_sha256 = excluded.checksum_sha256,
                    status = excluded.status,
                    profile_json = excluded.profile_json,
                    issues_json = excluded.issues_json,
                    deleted_at = excluded.deleted_at
                """,
                (
                    version.id,
                    version.dataset_id,
                    version.original_filename,
                    version.storage_key,
                    version.format,
                    version.size_bytes,
                    version.checksum_sha256,
                    version.status,
                    self._dump_json(version.profile.model_dump(mode="json")) if version.profile else None,
                    self._dump_json([issue.model_dump(mode="json") for issue in version.issues]),
                    version.created_at.isoformat(),
                    version.deleted_at.isoformat() if version.deleted_at else None,
                ),
            )
        return version

    def list_dataset_versions(self, dataset_id: str) -> list[DatasetVersion]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    dataset_id,
                    original_filename,
                    storage_key,
                    format,
                    size_bytes,
                    checksum_sha256,
                    status,
                    profile_json,
                    issues_json,
                    created_at,
                    deleted_at
                FROM dataset_versions
                WHERE dataset_id = ? AND status != 'deleted'
                ORDER BY created_at, id
                """,
                (dataset_id,),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def list_dataset_versions_by_status(self, statuses) -> list[DatasetVersion]:
        values = list(statuses)
        if not values:
            return []

        placeholders = ",".join("?" for _ in values)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    id,
                    dataset_id,
                    original_filename,
                    storage_key,
                    format,
                    size_bytes,
                    checksum_sha256,
                    status,
                    profile_json,
                    issues_json,
                    created_at,
                    deleted_at
                FROM dataset_versions
                WHERE status IN ({placeholders})
                ORDER BY created_at, id
                """,
                tuple(values),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def find_dataset_version_by_checksum(
        self,
        workspace_id: str,
        checksum_sha256: str,
    ) -> DatasetVersion | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    v.id,
                    v.dataset_id,
                    v.original_filename,
                    v.storage_key,
                    v.format,
                    v.size_bytes,
                    v.checksum_sha256,
                    v.status,
                    v.profile_json,
                    v.issues_json,
                    v.created_at,
                    v.deleted_at
                FROM dataset_versions v
                INNER JOIN datasets d ON d.id = v.dataset_id
                WHERE d.workspace_id = ?
                  AND v.checksum_sha256 = ?
                  AND v.status != 'deleted'
                ORDER BY v.created_at, v.id
                LIMIT 1
                """,
                (workspace_id, checksum_sha256),
            ).fetchone()
        return self._version_from_row(row) if row else None

    def count_versions_by_storage_key(self, storage_key: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM dataset_versions
                WHERE storage_key = ?
                """,
                (storage_key,),
            ).fetchone()
        return int(row[0])

    def purge_dataset_version(self, version_id: str) -> bool:
        with self._connection(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT id, status
                FROM dataset_versions
                WHERE id = ?
                """,
                (version_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] != "deleted":
                raise InvalidDatasetVersionPurgeError(
                    f"Dataset version {version_id} must be soft-deleted before purge"
                )

            cursor = conn.execute(
                """
                DELETE FROM dataset_versions
                WHERE id = ?
                  AND status = 'deleted'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM analysis_datasets
                      WHERE dataset_version_id = dataset_versions.id
                  )
                """,
                (version_id,),
            )
            if cursor.rowcount == 0:
                raise ReferencedDatasetVersionError(version_id)
        return cursor.rowcount > 0

    def save_analysis_dataset_selections(
        self,
        analysis_id: str,
        selections,
    ) -> list[AnalysisDatasetSelection]:
        items = list(selections)
        invalid = next((item for item in items if item.analysis_id != analysis_id), None)
        if invalid is not None:
            raise ValueError(
                f"Selection analysis_id {invalid.analysis_id} does not match {analysis_id}"
            )

        with self._connection() as conn:
            conn.execute(
                "DELETE FROM analysis_datasets WHERE analysis_id = ?",
                (analysis_id,),
            )
            conn.executemany(
                """
                INSERT INTO analysis_datasets (analysis_id, dataset_version_id, position)
                VALUES (?, ?, ?)
                """,
                [
                    (analysis_id, item.dataset_version_id, item.position)
                    for item in items
                ],
            )
        return items

    def list_analysis_dataset_selections(
        self,
        analysis_id: str,
    ) -> list[AnalysisDatasetSelection]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT analysis_id, dataset_version_id, position
                FROM analysis_datasets
                WHERE analysis_id = ?
                ORDER BY position, dataset_version_id
                """,
                (analysis_id,),
            ).fetchall()
        return [
            AnalysisDatasetSelection(
                analysis_id=row["analysis_id"],
                dataset_version_id=row["dataset_version_id"],
                position=row["position"],
            )
            for row in rows
        ]

    def is_version_referenced(self, version_id: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM analysis_datasets
                WHERE dataset_version_id = ?
                LIMIT 1
                """,
                (version_id,),
            ).fetchone()
        return row is not None

    def _initialize(self) -> None:
        with self._connection(immediate=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self._create_schema_v2(conn)
                conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
                return

            if version == 1:
                self._migrate_v1_to_v2(conn)
                conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
                return

            if version != self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported datasets schema version {version}; expected {self.SCHEMA_VERSION}"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _connection(self, *, immediate: bool = False):
        conn = self._connect()
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _workspace_from_row(row: sqlite3.Row) -> DataWorkspace:
        return DataWorkspace(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _dataset_from_row(row: sqlite3.Row) -> Dataset:
        return Dataset(
            id=row["id"],
            workspace_id=row["workspace_id"],
            display_name=row["display_name"],
            source_type=row["source_type"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @classmethod
    def _version_from_row(cls, row: sqlite3.Row) -> DatasetVersion:
        profile = None
        if row["profile_json"]:
            profile = DatasetProfile.model_validate(json.loads(row["profile_json"]))
        issues = []
        if row["issues_json"]:
            issues = [DatasetIssue.model_validate(item) for item in json.loads(row["issues_json"])]

        return DatasetVersion(
            id=row["id"],
            dataset_id=row["dataset_id"],
            original_filename=row["original_filename"],
            storage_key=row["storage_key"],
            format=row["format"],
            size_bytes=row["size_bytes"],
            checksum_sha256=row["checksum_sha256"],
            status=row["status"],
            profile=profile,
            issues=issues,
            created_at=datetime.fromisoformat(row["created_at"]),
            deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
        )

    @staticmethod
    def _dump_json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _create_schema_v2(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
            );

            CREATE TABLE IF NOT EXISTS dataset_versions (
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
                deleted_at TEXT,
                FOREIGN KEY (dataset_id) REFERENCES datasets(id)
            );

            CREATE TABLE IF NOT EXISTS analysis_datasets (
                analysis_id TEXT NOT NULL,
                dataset_version_id TEXT NOT NULL,
                position INTEGER NOT NULL CHECK (position >= 0),
                PRIMARY KEY (analysis_id, dataset_version_id),
                UNIQUE (analysis_id, position),
                FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_datasets_workspace_id
                ON datasets(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset_id
                ON dataset_versions(dataset_id);
            CREATE INDEX IF NOT EXISTS idx_dataset_versions_checksum
                ON dataset_versions(checksum_sha256);
            CREATE INDEX IF NOT EXISTS idx_dataset_versions_storage_key
                ON dataset_versions(storage_key);
            CREATE INDEX IF NOT EXISTS idx_analysis_datasets_version_id
                ON analysis_datasets(dataset_version_id);
            """
        )

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            ALTER TABLE analysis_datasets RENAME TO analysis_datasets_v1;

            CREATE TABLE analysis_datasets (
                analysis_id TEXT NOT NULL,
                dataset_version_id TEXT NOT NULL,
                position INTEGER NOT NULL CHECK (position >= 0),
                PRIMARY KEY (analysis_id, dataset_version_id),
                UNIQUE (analysis_id, position),
                FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id)
            );

            INSERT INTO analysis_datasets (analysis_id, dataset_version_id, position)
            SELECT analysis_id, dataset_version_id, position
            FROM analysis_datasets_v1;

            DROP TABLE analysis_datasets_v1;

            CREATE INDEX IF NOT EXISTS idx_analysis_datasets_version_id
                ON analysis_datasets(dataset_version_id);
            """
        )

    @staticmethod
    def _assert_dataset_immutable(existing: sqlite3.Row, dataset: Dataset) -> None:
        if existing["workspace_id"] != dataset.workspace_id:
            raise ImmutableDatasetError("workspace_id is immutable for Dataset")
        if existing["source_type"] != dataset.source_type:
            raise ImmutableDatasetError("source_type is immutable for Dataset")
        if existing["created_at"] != dataset.created_at.isoformat():
            raise ImmutableDatasetError("created_at is immutable for Dataset")

    @staticmethod
    def _assert_dataset_version_immutable(existing: sqlite3.Row, version: DatasetVersion) -> None:
        if existing["dataset_id"] != version.dataset_id:
            raise ImmutableDatasetVersionError("dataset_id is immutable for DatasetVersion")
        if existing["original_filename"] != version.original_filename:
            raise ImmutableDatasetVersionError("original_filename is immutable for DatasetVersion")
        if existing["created_at"] != version.created_at.isoformat():
            raise ImmutableDatasetVersionError("created_at is immutable for DatasetVersion")

        storage_fields = (
            ("storage_key", version.storage_key),
            ("format", version.format),
            ("size_bytes", version.size_bytes),
            ("checksum_sha256", version.checksum_sha256),
        )
        for field, new_value in storage_fields:
            current_value = existing[field]
            if current_value is not None and current_value != new_value:
                raise ImmutableDatasetVersionError(f"{field} cannot be changed once set")
