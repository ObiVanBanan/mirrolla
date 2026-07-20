"""
api/main.py — FastAPI для Mirrolla AI ассистента (M6).

Эндпоинты:
    POST /api/v1/analyses              — создать анализ (question → plan)
    GET  /api/v1/analyses/{id}         — статус + результат
    POST /api/v1/analyses/{id}/approve — подтвердить план → выполнить
    POST /api/v1/analyses/{id}/revise  — правка плана (period, product_code)
    POST /api/v1/analyses/{id}/reject  — отклонить план

    POST /api/v1/reports/management    — авто-отчёт (fixed workflow)

Запуск:
    PYTHONPATH= PYTHONHOME= ./venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000
"""

import os
import sys
import uuid
import json
import re
import time
import sqlite3
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field

# Убедиться что проектный root в sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()

from agent.router import route_sync
from agent.planner import plan as generate_plan
from agent.executor import execute as execute_plan
from agent.reporter import synthesize as reporter_synthesize
from agent.schemas import AnalysisPlan, ExecutionResult, SkillType, Finding

# === Конфигурация ===

CHECKPOINT_DB = os.path.join(PROJECT_ROOT, "data", "checkpoints.sqlite")
ANALYSES_DB = os.path.join(PROJECT_ROOT, "data", "analyses.sqlite")

# API key auth
API_KEY = os.getenv("API_KEY", "")

# CORS origins
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").strip()
if CORS_ORIGINS:
    CORS_ORIGINS_LIST = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
else:
    CORS_ORIGINS_LIST = ["*"]

# === SQLite ===

_db_initialized = False


def _get_analyses_conn():
    """SQLite connection для хранения метаданных анализов."""
    global _db_initialized
    os.makedirs(os.path.dirname(ANALYSES_DB), exist_ok=True)
    conn = sqlite3.connect(ANALYSES_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    if not _db_initialized:
        _init_analyses_db(conn)
        _db_initialized = True
    return conn


def _init_analyses_db(conn):
    """Создать таблицу analyses если нет."""
    conn.execute("""
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
    """)
    conn.commit()


# === Rate limiter (in-memory, per IP) ===

_rate_log: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # секунд
RATE_LIMIT_MAX = 10  # запросов в окно


def _check_rate_limit(client_ip: str):
    """Проверить лимит запросов для IP. Raises 429 если превышен."""
    now = time.time()
    timestamps = _rate_log[client_ip]
    # чистим старые
    _rate_log[client_ip] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_log[client_ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много запросов. Лимит: {RATE_LIMIT_MAX} в {RATE_LIMIT_WINDOW}с.",
        )
    _rate_log[client_ip].append(now)


# === API Key auth ===

def verify_api_key(x_api_key: str = Header(default="")):
    """Проверить API ключ. Если API_KEY пуст — auth отключена (dev mode)."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Неверный API ключ")


def _validate_analysis_id(analysis_id: str):
    """Валидация analysis_id: alphanumeric + hyphens, max 64 символа."""
    if not re.match(r"^[a-zA-Z0-9\-]{1,64}$", analysis_id):
        raise HTTPException(status_code=400, detail="Некорректный analysis_id")


# === Pydantic models для API ===

class CreateAnalysisRequest(BaseModel):
    question: str = Field(..., description="Вопрос менеджера")


class ReviseRequest(BaseModel):
    feedback: str = Field(..., description="Правка: например 'период 30 дней, товар ЦБ-00049405'")


class AnalysisResponse(BaseModel):
    id: str
    question: str
    skill: Optional[str] = None
    status: str
    plan: Optional[dict] = None
    result: Optional[dict] = None
    created_at: str
    updated_at: str


# === FastAPI app ===

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация БД при старте."""
    _get_analyses_conn()
    print(f"[API] Analyses DB: {ANALYSES_DB}")
    yield


app = FastAPI(
    title="Mirrolla AI Assistant",
    description="Аналитический ассистент для маркетплейсов WB+Ozon",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — для UI на file:// или другом порту
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS_LIST,
    allow_credentials=CORS_ORIGINS_LIST != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UI_INDEX = os.path.join(PROJECT_ROOT, "ui", "mirrolla_assistant.html")


@app.get("/", include_in_schema=False)
async def main_page():
    if not os.path.exists(UI_INDEX):
        raise HTTPException(
            status_code=404,
            detail="Файл ui/mirrolla_assistant.html не найден",
        )

    return FileResponse(UI_INDEX)


# === Эндпоинты ===

@app.post("/api/v1/analyses", response_model=AnalysisResponse)
def create_analysis(
    req: CreateAnalysisRequest,
    request: Request,
    _: None = Depends(verify_api_key),
):
    """Создать анализ: question → Router → Planner → план.

    Возвращает analysis_id + план. Статус: awaiting_approval.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question не может быть пустым")

    _check_rate_limit(request.client.host if request.client else "unknown")

    analysis_id = str(uuid.uuid4())

    # Router
    routing = route_sync(req.question)

    # Planner
    plan = generate_plan(req.question, routing=routing)

    # Сохранить в БД
    conn = _get_analyses_conn()
    try:
        conn.execute(
            "INSERT INTO analyses (id, question, skill, status, plan_json) VALUES (?, ?, ?, ?, ?)",
            (analysis_id, req.question, plan.skill.value, "awaiting_approval",
             json.dumps(plan.model_dump(), ensure_ascii=False, default=str))
        )
        conn.commit()

        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    finally:
        conn.close()

    return _row_to_response(row)


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: str):
    """Получить статус + результат анализа."""
    _validate_analysis_id(analysis_id)
    conn = _get_analyses_conn()
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")

    return _row_to_response(row)


@app.post("/api/v1/analyses/{analysis_id}/approve", response_model=AnalysisResponse)
def approve_analysis(
    analysis_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    _: None = Depends(verify_api_key),
):
    """Подтвердить план → запустить выполнение (async).

    Возвращает статус executing. Результат можно получить через GET.
    """
    _validate_analysis_id(analysis_id)
    _check_rate_limit(request.client.host if request.client else "unknown")

    conn = _get_analyses_conn()
    try:
        # Атомарная проверка и обновление статуса — защита от race condition
        cursor = conn.execute(
            "UPDATE analyses SET status = 'executing', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'awaiting_approval'",
            (analysis_id,)
        )
        conn.commit()

        if cursor.rowcount == 0:
            # Либо не найден, либо не в статусе awaiting_approval
            row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")
            raise HTTPException(
                status_code=400,
                detail=f"Анализ в статусе {row['status']}, нельзя approve"
            )

        # Запустить выполнение в фоне
        background_tasks.add_task(_execute_analysis_background, analysis_id)
    finally:
        conn.close()

    return _row_to_response(row=None, analysis_id=analysis_id, status="executing")


@app.post("/api/v1/analyses/{analysis_id}/revise", response_model=AnalysisResponse)
def revise_analysis(
    analysis_id: str,
    req: ReviseRequest,
    request: Request,
    _: None = Depends(verify_api_key),
):
    """Правка плана: обновить период/product_code → пересобрать план."""
    _validate_analysis_id(analysis_id)
    _check_rate_limit(request.client.host if request.client else "unknown")

    conn = _get_analyses_conn()
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")
        if row["status"] != "awaiting_approval":
            raise HTTPException(
                status_code=400,
                detail=f"Анализ в статусе {row['status']}, нельзя revise"
            )

        # Загрузить текущий план
        plan_dict = json.loads(row["plan_json"])
        plan = AnalysisPlan(**plan_dict)

        # Парсинг feedback → обновление routing
        feedback = req.feedback
        updates = {}
        period_match = re.search(r"период\s*(\d+)", feedback.lower())
        if period_match:
            updates["period_days"] = int(period_match.group(1))
        code_match = re.findall(r"(?:ЦБ|ФР)-\d{8}", feedback)
        if code_match:
            updates["product_codes"] = code_match

        # Пересобрать plan с обновлённым routing
        from agent.schemas import RoutingResult, PeriodSpec
        routing = RoutingResult(
            skill=plan.skill,
            product_codes=updates.get("product_codes", plan.product_codes),
            period_days=updates.get("period_days", plan.period.current_days),
        )
        new_plan = generate_plan(row["question"], routing=routing)

        conn.execute(
            "UPDATE analyses SET plan_json = ?, status = 'awaiting_approval', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(new_plan.model_dump(), ensure_ascii=False, default=str), analysis_id)
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
    """Отклонить план."""
    _validate_analysis_id(analysis_id)
    _check_rate_limit(request.client.host if request.client else "unknown")

    conn = _get_analyses_conn()
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")

        conn.execute(
            "UPDATE analyses SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (analysis_id,)
        )
        conn.commit()
    finally:
        conn.close()

    return _row_to_response(row=None, analysis_id=analysis_id, status="rejected")


@app.post("/api/v1/reports/management")
def management_report(
    background_tasks: BackgroundTasks,
    request: Request,
    _: None = Depends(verify_api_key),
):
    """Авто-отчёт: fixed workflow (топ-10 рост, топ-10 падение, критические остатки, отзывы).

    Запускает 4 анализа параллельно и собирает результаты.
    """
    _check_rate_limit(request.client.host if request.client else "unknown")

    questions = [
        "Что растёт быстрее рынка?",
        "Топ-10 падающих товаров",
        "Какие товары заканчиваются?",
        "Какие отзывы требуют реакции?",
    ]
    report_id = str(uuid.uuid4())

    # Создаём 4 анализа
    analysis_ids = []
    conn = _get_analyses_conn()
    try:
        for q in questions:
            aid = str(uuid.uuid4())
            routing = route_sync(q)
            plan = generate_plan(q, routing=routing)
            conn.execute(
                "INSERT INTO analyses (id, question, skill, status, plan_json) VALUES (?, ?, ?, ?, ?)",
                (aid, q, plan.skill.value, "executing",
                 json.dumps(plan.model_dump(), ensure_ascii=False, default=str))
            )
            analysis_ids.append(aid)
            # Запускаем в фоне
            background_tasks.add_task(_execute_analysis_background, aid)
        conn.commit()
    finally:
        conn.close()

    return {
        "report_id": report_id,
        "analysis_ids": analysis_ids,
        "status": "executing",
        "message": "Отчёт формируется. Результаты доступны через GET /api/v1/analyses/{id}",
    }


@app.get("/api/v1/health")
def health():
    """Health check."""
    return {"status": "ok", "service": "mirrolla-ai"}


# === Background task: выполнение анализа ===

def _execute_analysis_background(analysis_id: str):
    """Выполнить анализ в background task.

    Загружает план из БД, запускает executor + reporter, сохраняет результат.
    """
    conn = _get_analyses_conn()
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    if not row:
        conn.close()
        return

    try:
        plan_dict = json.loads(row["plan_json"])
        plan = AnalysisPlan(**plan_dict)

        # Executor + Reporter (уже встроен в execute)
        result = execute_plan(plan)

        # Сохранить результат
        conn.execute(
            "UPDATE analyses SET status = 'done', result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(result.model_dump(), ensure_ascii=False, default=str), analysis_id)
        )
        conn.commit()
        print(f"[API] Analysis {analysis_id[:8]} done: {len(result.findings)} findings")
    except Exception as e:
        print(f"[API] Analysis {analysis_id[:8]} failed: {e}")
        conn.execute(
            "UPDATE analyses SET status = 'error', result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps({"error": str(e)}, ensure_ascii=False), analysis_id)
        )
        conn.commit()
    finally:
        conn.close()


# === Утилиты ===

def _row_to_response(row=None, analysis_id=None, status=None):
    """Преобразовать строку БД в AnalysisResponse."""
    if row is None and analysis_id:
        return AnalysisResponse(
            id=analysis_id,
            question="",
            skill=None,
            status=status or "unknown",
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
        plan=plan,
        result=result,
        created_at=str(row["created_at"]) if row["created_at"] else "",
        updated_at=str(row["updated_at"]) if row["updated_at"] else "",
    )


# === Entry point для uvicorn ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)