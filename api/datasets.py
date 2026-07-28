from __future__ import annotations

from pathlib import Path
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from application.datasets.models import Dataset, DataWorkspace, DatasetVersion
from application.datasets.service import (
    DatasetNotFoundError,
    DatasetServiceError,
    DatasetVersionNotFoundError,
    InvalidDatasetStateError,
    WorkspaceNotFoundError,
)
from infrastructure.storage.local_files import (
    EmptyFileError,
    FileTooLargeError,
    InvalidFilenameError,
    StreamReadError,
    UnsupportedExtensionError,
)

logger = logging.getLogger(__name__)


def build_datasets_router(*, verify_api_key, check_mutation_rate_limit, check_poll_rate_limit):
    router = APIRouter(prefix="/api/v1", tags=["datasets"])

    class WorkspaceResponse(BaseModel):
        id: str
        name: str
        created_at: str

    class DatasetVersionResponse(BaseModel):
        id: str
        dataset_id: str
        original_filename: str
        format: str | None = None
        size_bytes: int | None = None
        checksum_sha256: str | None = None
        status: str
        created_at: str
        deleted_at: str | None = None

    class DatasetResponse(BaseModel):
        id: str
        workspace_id: str
        display_name: str
        source_type: str
        created_at: str
        versions: list[DatasetVersionResponse] = Field(default_factory=list)

    class DatasetListResponse(BaseModel):
        workspace: WorkspaceResponse
        datasets: list[DatasetResponse] = Field(default_factory=list)

    class DatasetProfileResponse(BaseModel):
        version_id: str
        status: str
        profile: dict | None = None
        issues: list[dict] = Field(default_factory=list)

    class UploadDatasetResponse(BaseModel):
        dataset: DatasetResponse
        version: DatasetVersionResponse
        deduplicated: bool

    class DeleteDatasetVersionResponse(BaseModel):
        version: DatasetVersionResponse

    def _dataset_repository(request: Request):
        return request.app.state.dataset_repository_factory()

    def _dataset_service(request: Request):
        return request.app.state.dataset_service_factory()

    def _raw_file_storage(request: Request):
        return request.app.state.raw_file_storage_factory()

    def _max_upload_bytes(request: Request) -> int:
        return request.app.state.max_upload_bytes

    def _workspace_response(workspace: DataWorkspace) -> WorkspaceResponse:
        return WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            created_at=workspace.created_at.isoformat(),
        )

    def _version_response(version: DatasetVersion) -> DatasetVersionResponse:
        return DatasetVersionResponse(
            id=version.id,
            dataset_id=version.dataset_id,
            original_filename=version.original_filename,
            format=version.format,
            size_bytes=version.size_bytes,
            checksum_sha256=version.checksum_sha256,
            status=version.status,
            created_at=version.created_at.isoformat(),
            deleted_at=version.deleted_at.isoformat() if version.deleted_at else None,
        )

    def _dataset_response(dataset: Dataset, versions: list[DatasetVersion]) -> DatasetResponse:
        return DatasetResponse(
            id=dataset.id,
            workspace_id=dataset.workspace_id,
            display_name=dataset.display_name,
            source_type=dataset.source_type,
            created_at=dataset.created_at.isoformat(),
            versions=[_version_response(version) for version in versions],
        )

    def _handle_dataset_error(exc: Exception) -> HTTPException:
        if isinstance(
            exc,
            (WorkspaceNotFoundError, DatasetNotFoundError, DatasetVersionNotFoundError),
        ):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, InvalidDatasetStateError):
            return HTTPException(status_code=409, detail=str(exc))
        if isinstance(exc, UnsupportedExtensionError):
            return HTTPException(status_code=415, detail=str(exc))
        if isinstance(exc, FileTooLargeError):
            return HTTPException(status_code=413, detail=str(exc))
        if isinstance(exc, (InvalidFilenameError, EmptyFileError, StreamReadError)):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, DatasetServiceError):
            return HTTPException(status_code=409, detail=str(exc))
        logger.exception("Dataset API failure")
        return HTTPException(status_code=500, detail="Internal dataset operation failed")

    @router.get("/workspaces/default", response_model=WorkspaceResponse)
    def get_default_workspace(
        request: Request,
        _: None = Depends(verify_api_key),
    ):
        check_poll_rate_limit(request.client.host if request.client else "unknown")
        workspace = _dataset_service(request).ensure_default_workspace()
        return _workspace_response(workspace)

    @router.get("/workspaces/{workspace_id}/datasets", response_model=DatasetListResponse)
    def list_datasets(
        workspace_id: str,
        request: Request,
        _: None = Depends(verify_api_key),
    ):
        check_poll_rate_limit(request.client.host if request.client else "unknown")
        repository = _dataset_repository(request)
        workspace = repository.get_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} was not found")

        datasets = repository.list_datasets(workspace_id)
        return DatasetListResponse(
            workspace=_workspace_response(workspace),
            datasets=[
                _dataset_response(dataset, repository.list_dataset_versions(dataset.id))
                for dataset in datasets
            ],
        )

    @router.post("/workspaces/{workspace_id}/datasets", response_model=UploadDatasetResponse)
    def upload_dataset(
        workspace_id: str,
        request: Request,
        file: UploadFile = File(...),
        display_name: str | None = Form(default=None),
        dataset_id: str | None = Form(default=None),
        _: None = Depends(verify_api_key),
    ):
        check_mutation_rate_limit(request.client.host if request.client else "unknown")
        service = _dataset_service(request)
        repository = _dataset_repository(request)
        storage = _raw_file_storage(request)
        created_new_dataset = dataset_id is None
        dataset = None
        version = None
        stored = None
        try:
            dataset, version = service.register_upload_receiving(
                workspace_id,
                original_filename=file.filename or "",
                display_name=display_name,
                dataset_id=dataset_id,
            )
            stored = storage.put_stream(
                workspace_id=workspace_id,
                dataset_id=dataset.id,
                version_id=version.id,
                original_filename=file.filename or "",
                stream=file.file,
                max_bytes=_max_upload_bytes(request),
            )
            suffix = Path(file.filename or "").suffix.lower().lstrip(".")
            uploaded = service.complete_upload(
                version.id,
                storage_key=stored.storage_key,
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                file_format=suffix,
            )
            profiling = service.start_profiling(uploaded.id)
            return UploadDatasetResponse(
                dataset=_dataset_response(dataset, repository.list_dataset_versions(dataset.id)),
                version=_version_response(profiling),
                deduplicated=stored.deduplicated,
            )
        except Exception as exc:
            if version is not None:
                try:
                    service.soft_delete_version(version.id)
                    repository.purge_dataset_version(version.id)
                except Exception:
                    pass
            if stored is not None:
                try:
                    if repository.count_versions_by_storage_key(stored.storage_key) == 0:
                        storage.delete(stored.storage_key)
                except Exception:
                    logger.exception("Failed to clean orphaned dataset blob")
            if dataset is not None and created_new_dataset:
                try:
                    repository.delete_dataset_if_empty(dataset.id)
                except Exception:
                    logger.exception("Failed to delete empty dataset after upload rollback")
            raise _handle_dataset_error(exc)
        finally:
            file.file.close()

    @router.get("/dataset-versions/{version_id}", response_model=DatasetVersionResponse)
    def get_dataset_version(
        version_id: str,
        request: Request,
        _: None = Depends(verify_api_key),
    ):
        check_poll_rate_limit(request.client.host if request.client else "unknown")
        version = _dataset_repository(request).get_dataset_version(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail=f"Dataset version {version_id} was not found")
        return _version_response(version)

    @router.get("/dataset-versions/{version_id}/profile", response_model=DatasetProfileResponse)
    def get_dataset_version_profile(
        version_id: str,
        request: Request,
        _: None = Depends(verify_api_key),
    ):
        check_poll_rate_limit(request.client.host if request.client else "unknown")
        version = _dataset_repository(request).get_dataset_version(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail=f"Dataset version {version_id} was not found")
        return DatasetProfileResponse(
            version_id=version.id,
            status=version.status,
            profile=version.profile.model_dump(mode="json") if version.profile else None,
            issues=[issue.model_dump(mode="json") for issue in version.issues],
        )

    @router.delete("/dataset-versions/{version_id}", response_model=DeleteDatasetVersionResponse)
    def delete_dataset_version(
        version_id: str,
        request: Request,
        _: None = Depends(verify_api_key),
    ):
        check_mutation_rate_limit(request.client.host if request.client else "unknown")
        try:
            deleted = _dataset_service(request).soft_delete_version(version_id)
            return DeleteDatasetVersionResponse(version=_version_response(deleted))
        except Exception as exc:
            raise _handle_dataset_error(exc)

    return router
