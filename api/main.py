"""
FastAPI entrypoint for Mirrolla.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()

from agent.planner import plan as generate_plan
from agent.router import route_sync
from agent.schemas import AnalysisPlan
from api.datasets import build_datasets_router
from application.datasets.models import Dataset, DatasetVersion
from application.datasets.service import (
    DatasetNotFoundError,
    DatasetService,
    DatasetServiceError,
    DatasetVersionNotFoundError,
    InvalidDatasetStateError,
    WorkspaceNotFoundError,
)
from infrastructure.jobs.in_process_dispatcher import InProcessDatasetJobDispatcher
from infrastructure.persistence.sqlite_datasets import SqliteDatasetRepository
from infrastructure.storage.local_files import LocalRawFileStorage


CHECKPOINT_DB = os.path.join(PROJECT_ROOT, "data", "checkpoints.sqlite")
ANALYSES_DB = os.path.join(PROJECT_ROOT, "data", "analyses.sqlite")
DATASETS_DB = os.path.join(PROJECT_ROOT, "data", "datasets.sqlite")
UPLOADS_ROOT = os.path.join(PROJECT_ROOT, "data", "uploads")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))

API_KEY = os.getenv("API_KEY", "")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").strip()
CORS_ORIGINS_LIST = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()] if CORS_ORIGINS else ["*"]

_db_initialized = False
_mutation_rate_log: dict[str, list[float]] = defaultdict(list)
_poll_rate_log: dict[str, list[float]] = defaultdict(list)
MUTATION_RATE_LIMIT_WINDOW = 60
MUTATION_RATE_LIMIT_MAX = 10
POLL_RATE_LIMIT_WINDOW = 60
POLL_RATE_LIMIT_MAX = 120
_rate_log = _mutation_rate_log


def _get_analyses_conn():
    global _db_initialized
    os.makedirs(os.path.dirname(ANALYSES_DB), exist_ok=True)
    conn = sqlite3.connect(ANALYSES_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    if not _db_initialized:
        _init_analyses_db(conn)
        _db_initialized = True
    return conn


def _init_analyses_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            skill TEXT,
            status TEXT DEFAULT 'planning',
            plan_json TEXT,
            result_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def _check_mutation_rate_limit(client_ip: str) -> None:
    now = time.time()
    timestamps = _mutation_rate_log[client_ip]
    _mutation_rate_log[client_ip] = [
        timestamp
        for timestamp in timestamps
        if now - timestamp < MUTATION_RATE_LIMIT_WINDOW
    ]
    if len(_mutation_rate_log[client_ip]) >= MUTATION_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many requests. Limit: {MUTATION_RATE_LIMIT_MAX} in "
                f"{MUTATION_RATE_LIMIT_WINDOW}s."
            ),
        )
    _mutation_rate_log[client_ip].append(now)


def _check_poll_rate_limit(client_ip: str) -> None:
    now = time.time()
    timestamps = _poll_rate_log[client_ip]
    _poll_rate_log[client_ip] = [
        timestamp
        for timestamp in timestamps
        if now - timestamp < POLL_RATE_LIMIT_WINDOW
    ]
    if len(_poll_rate_log[client_ip]) >= POLL_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Too many polling requests. Limit: {POLL_RATE_LIMIT_MAX} in {POLL_RATE_LIMIT_WINDOW}s.",
        )
    _poll_rate_log[client_ip].append(now)


def verify_api_key(x_api_key: str = Header(default="")):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _validate_analysis_id(analysis_id: str) -> None:
    if not re.match(r"^[a-zA-Z0-9\-]{1,64}$", analysis_id):
        raise HTTPException(status_code=400, detail="Invalid analysis_id")


class CreateAnalysisRequest(BaseModel):
    question: str = Field(..., description="Manager question")
    dataset_version_ids: list[str] = Field(default_factory=list)


class ReviseRequest(BaseModel):
    feedback: str = Field(..., description="Plan revision feedback")


class AnalysisDatasetAttachmentResponse(BaseModel):
    dataset_id: str
    dataset_version_id: str
    display_name: str
    original_filename: str
    format: str | None = None
    status: str
    checksum_sha256: str | None = None
    created_at: str


class AnalysisResponse(BaseModel):
    id: str
    question: str
    skill: Optional[str] = None
    status: str
    dataset_version_ids: list[str] = Field(default_factory=list)
    dataset_attachments: list[AnalysisDatasetAttachmentResponse] = Field(default_factory=list)
    plan: Optional[dict] = None
    result: Optional[dict] = None
    created_at: str
    updated_at: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = _get_analyses_conn()
    conn.close()
    app.state.dataset_repository_factory = lambda: SqliteDatasetRepository(DATASETS_DB)
    app.state.raw_file_storage_factory = lambda: LocalRawFileStorage(UPLOADS_ROOT)
    app.state.dataset_job_dispatcher = InProcessDatasetJobDispatcher(
        repository_factory=app.state.dataset_repository_factory,
        storage_factory=app.state.raw_file_storage_factory,
    )
    app.state.dataset_service_factory = lambda: DatasetService(
        app.state.dataset_repository_factory(),
        app.state.dataset_job_dispatcher,
    )
    app.state.max_upload_bytes = MAX_UPLOAD_BYTES
    repository = app.state.dataset_repository_factory()
    app.state.dataset_service_factory().ensure_default_workspace()
    for version in repository.list_dataset_versions_by_status(["profiling"]):
        app.state.dataset_job_dispatcher.dispatch_profile(version.id)
    try:
        yield
    finally:
        app.state.dataset_job_dispatcher.shutdown()


app = FastAPI(
    title="Mirrolla AI Assistant",
    description="Marketplace analytics assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS_LIST,
    allow_credentials=CORS_ORIGINS_LIST != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    build_datasets_router(
        verify_api_key=verify_api_key,
        check_mutation_rate_limit=_check_mutation_rate_limit,
        check_poll_rate_limit=_check_poll_rate_limit,
    )
)

UI_INDEX = os.path.join(PROJECT_ROOT, "ui", "mirrolla_assistant.html")
DATASET_WORKSPACE_JS = os.path.join(PROJECT_ROOT, "ui", "dataset_workspace.js")


@app.get("/", include_in_schema=False)
async def main_page():
    if not os.path.exists(UI_INDEX):
        raise HTTPException(status_code=404, detail="ui/mirrolla_assistant.html not found")
    return FileResponse(UI_INDEX)


@app.get("/ui/dataset_workspace.js", include_in_schema=False)
async def dataset_workspace_script():
    if not os.path.exists(DATASET_WORKSPACE_JS):
        raise HTTPException(status_code=404, detail="ui/dataset_workspace.js not found")
    return FileResponse(DATASET_WORKSPACE_JS, media_type="application/javascript")


@app.post("/api/v1/analyses", response_model=AnalysisResponse)
def create_analysis(
    req: CreateAnalysisRequest,
    request: Request,
    _: None = Depends(verify_api_key),
):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")

    _check_mutation_rate_limit(request.client.host if request.client else "unknown")

    analysis_id = str(uuid.uuid4())
    routing = route_sync(req.question)
    plan = generate_plan(req.question, routing=routing)
    dataset_service = app.state.dataset_service_factory()

    conn = _get_analyses_conn()
    try:
        conn.execute(
            "INSERT INTO analyses (id, question, skill, status, plan_json) VALUES (?, ?, ?, ?, ?)",
            (
                analysis_id,
                req.question,
                plan.skill.value,
                "awaiting_approval",
                json.dumps(plan.model_dump(), ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
        try:
            dataset_service.attach_versions_to_analysis(
                analysis_id,
                req.dataset_version_ids,
            )
        except Exception as exc:
            conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
            conn.commit()
            if isinstance(
                exc,
                (DatasetVersionNotFoundError, DatasetNotFoundError, WorkspaceNotFoundError),
            ):
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if isinstance(exc, (InvalidDatasetStateError, DatasetServiceError)):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    finally:
        conn.close()

    return _row_to_response(row)


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: str):
    _validate_analysis_id(analysis_id)
    conn = _get_analyses_conn()
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")

    return _row_to_response(row)


@app.post("/api/v1/analyses/{analysis_id}/approve", response_model=AnalysisResponse)
def approve_analysis(
    analysis_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    _: None = Depends(verify_api_key),
):
    _validate_analysis_id(analysis_id)
    _check_mutation_rate_limit(request.client.host if request.client else "unknown")

    conn = _get_analyses_conn()
    try:
        cursor = conn.execute(
            "UPDATE analyses SET status = 'executing', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'awaiting_approval'",
            (analysis_id,),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

        if cursor.rowcount == 0:
            if not row:
                raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")
            raise HTTPException(
                status_code=400,
                detail=f"Analysis is in status {row['status']}, cannot approve",
            )

        background_tasks.add_task(_execute_analysis_background, analysis_id)
    finally:
        conn.close()

    return _row_to_response(row)


@app.post("/api/v1/analyses/{analysis_id}/revise", response_model=AnalysisResponse)
def revise_analysis(
    analysis_id: str,
    req: ReviseRequest,
    request: Request,
    _: None = Depends(verify_api_key),
):
    _validate_analysis_id(analysis_id)
    _check_mutation_rate_limit(request.client.host if request.client else "unknown")

    conn = _get_analyses_conn()
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")
        if row["status"] != "awaiting_approval":
            raise HTTPException(
                status_code=400,
                detail=f"Analysis is in status {row['status']}, cannot revise",
            )

        plan_dict = json.loads(row["plan_json"])
        plan = AnalysisPlan(**plan_dict)

        feedback = req.feedback
        updates: dict[str, object] = {}
        period_match = re.search(r"period\s*(\d+)|период\s*(\d+)", feedback.lower())
        if period_match:
            value = period_match.group(1) or period_match.group(2)
            updates["period_days"] = int(value)
        code_match = re.findall(r"(?:ЦБ|ФР)-\d{8}", feedback)
        if code_match:
            updates["product_codes"] = code_match

        from agent.schemas import RoutingResult

        routing = RoutingResult(
            skill=plan.skill,
            product_codes=updates.get("product_codes", plan.product_codes),
            period_days=updates.get("period_days", plan.period.current_days),
        )
        new_plan = generate_plan(row["question"], routing=routing)

        conn.execute(
            "UPDATE analyses SET plan_json = ?, status = 'awaiting_approval', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(new_plan.model_dump(), ensure_ascii=False, default=str), analysis_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    finally:
        conn.close()

    return _row_to_response(row)


@app.post("/api/v1/analyses/{analysis_id}/reject", response_model=AnalysisResponse)
def reject_analysis(
    analysis_id: str,
    request: Request,
    _: None = Depends(verify_api_key),
):
    _validate_analysis_id(analysis_id)
    _check_mutation_rate_limit(request.client.host if request.client else "unknown")

    conn = _get_analyses_conn()
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")
        conn.execute(
            "UPDATE analyses SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (analysis_id,),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    finally:
        conn.close()

    return _row_to_response(row)


@app.post("/api/v1/reports/management")
def management_report(
    background_tasks: BackgroundTasks,
    request: Request,
    _: None = Depends(verify_api_key),
):
    _check_mutation_rate_limit(request.client.host if request.client else "unknown")

    questions = [
        "Что растёт быстрее рынка?",
        "Топ-10 падающих товаров",
        "Какие товары заканчиваются?",
        "Какие отзывы требуют реакции?",
    ]
    report_id = str(uuid.uuid4())

    analysis_ids: list[str] = []
    conn = _get_analyses_conn()
    try:
        for question in questions:
            aid = str(uuid.uuid4())
            routing = route_sync(question)
            plan = generate_plan(question, routing=routing)
            conn.execute(
                "INSERT INTO analyses (id, question, skill, status, plan_json) VALUES (?, ?, ?, ?, ?)",
                (
                    aid,
                    question,
                    plan.skill.value,
                    "executing",
                    json.dumps(plan.model_dump(), ensure_ascii=False, default=str),
                ),
            )
            analysis_ids.append(aid)
            background_tasks.add_task(_execute_analysis_background, aid)
        conn.commit()
    finally:
        conn.close()

    return {
        "report_id": report_id,
        "analysis_ids": analysis_ids,
        "status": "executing",
        "message": "Report is being generated. Results are available via GET /api/v1/analyses/{id}",
    }


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "mirrolla-ai"}


def _execute_analysis_background(analysis_id: str) -> None:
    conn = _get_analyses_conn()
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    if not row:
        conn.close()
        return

    try:
        plan_dict = json.loads(row["plan_json"])
        plan = AnalysisPlan(**plan_dict)
        from agent.executor import execute as execute_plan

        result = execute_plan(plan)
        conn.execute(
            "UPDATE analyses SET status = 'done', result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(result.model_dump(), ensure_ascii=False, default=str), analysis_id),
        )
        conn.commit()
    except Exception as exc:
        conn.execute(
            "UPDATE analyses SET status = 'error', result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps({"error": str(exc)}, ensure_ascii=False), analysis_id),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_response(row=None, analysis_id=None, status=None):
    dataset_version_ids = _get_analysis_dataset_version_ids(
        analysis_id or (row["id"] if row is not None else None)
    )
    dataset_attachments = _get_analysis_dataset_attachments(
        analysis_id or (row["id"] if row is not None else None)
    )

    if row is None and analysis_id:
        return AnalysisResponse(
            id=analysis_id,
            question="",
            skill=None,
            status=status or "unknown",
            dataset_version_ids=dataset_version_ids,
            dataset_attachments=dataset_attachments,
            plan=None,
            result=None,
            created_at="",
            updated_at="",
        )

    plan = json.loads(row["plan_json"]) if row["plan_json"] else None
    result = json.loads(row["result_json"]) if row["result_json"] else None

    return AnalysisResponse(
        id=row["id"],
        question=row["question"],
        skill=row["skill"],
        status=row["status"],
        dataset_version_ids=dataset_version_ids,
        dataset_attachments=dataset_attachments,
        plan=plan,
        result=result,
        created_at=str(row["created_at"]) if row["created_at"] else "",
        updated_at=str(row["updated_at"]) if row["updated_at"] else "",
    )


def _get_analysis_dataset_version_ids(analysis_id: str | None) -> list[str]:
    if not analysis_id:
        return []

    repository = app.state.dataset_repository_factory()
    selections = repository.list_analysis_dataset_selections(analysis_id)
    return [selection.dataset_version_id for selection in selections]


def _get_analysis_dataset_attachments(
    analysis_id: str | None,
) -> list[AnalysisDatasetAttachmentResponse]:
    if not analysis_id:
        return []

    repository = app.state.dataset_repository_factory()
    attachments: list[AnalysisDatasetAttachmentResponse] = []
    for selection in repository.list_analysis_dataset_selections(analysis_id):
        version = repository.get_dataset_version(selection.dataset_version_id)
        if version is None:
            continue

        dataset = repository.get_dataset(version.dataset_id)
        if dataset is None:
            continue

        attachments.append(_build_analysis_dataset_attachment(dataset, version))
    return attachments


def _build_analysis_dataset_attachment(
    dataset: Dataset,
    version: DatasetVersion,
) -> AnalysisDatasetAttachmentResponse:
    return AnalysisDatasetAttachmentResponse(
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        display_name=dataset.display_name,
        original_filename=version.original_filename,
        format=version.format,
        status=version.status,
        checksum_sha256=version.checksum_sha256,
        created_at=version.created_at.isoformat(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
