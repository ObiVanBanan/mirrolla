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
import sqlite3
import asyncio
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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


def _get_analyses_conn():
    """SQLite connection для хранения метаданных анализов."""
    os.makedirs(os.path.dirname(ANALYSES_DB), exist_ok=True)
    conn = sqlite3.connect(ANALYSES_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_analyses_db(conn)
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

app = FastAPI(
    title="Mirrolla AI Assistant",
    description="Аналитический ассистент для маркетплейсов WB+Ozon",
    version="1.0.0",
)

# CORS — для UI на file:// или другом порту
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev: можно ограничить для prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """Инициализация БД при старте."""
    _get_analyses_conn()
    print(f"[API] Analyses DB: {ANALYSES_DB}")


# === Эндпоинты ===

@app.post("/api/v1/analyses", response_model=AnalysisResponse)
async def create_analysis(req: CreateAnalysisRequest):
    """Создать анализ: question → Router → Planner → план.

    Возвращает analysis_id + план. Статус: awaiting_approval.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question не может быть пустым")

    analysis_id = str(uuid.uuid4())

    # Router
    routing = route_sync(req.question)

    # Planner
    plan = generate_plan(req.question, routing=routing)

    # Сохранить в БД
    conn = _get_analyses_conn()
    conn.execute(
        "INSERT INTO analyses (id, question, skill, status, plan_json) VALUES (?, ?, ?, ?, ?)",
        (analysis_id, req.question, plan.skill.value, "awaiting_approval",
         json.dumps(plan.model_dump(), ensure_ascii=False, default=str))
    )
    conn.commit()

    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    conn.close()

    return _row_to_response(row)


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(analysis_id: str):
    """Получить статус + результат анализа."""
    conn = _get_analyses_conn()
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")

    return _row_to_response(row)


@app.post("/api/v1/analyses/{analysis_id}/approve", response_model=AnalysisResponse)
async def approve_analysis(analysis_id: str, background_tasks: BackgroundTasks):
    """Подтвердить план → запустить выполнение (async).

    Возвращает статус executing. Результат можно получить через GET.
    """
    conn = _get_analyses_conn()
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")

    if row["status"] not in ("awaiting_approval",):
        conn.close()
        raise HTTPException(status_code=400, detail=f"Анализ в статусе {row['status']}, нельзя approve")

    # Обновить статус
    conn.execute("UPDATE analyses SET status = 'executing', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                 (analysis_id,))
    conn.commit()
    conn.close()

    # Запустить выполнение в фоне
    background_tasks.add_task(_execute_analysis_background, analysis_id)

    return _row_to_response(row=None, analysis_id=analysis_id, status="executing")


@app.post("/api/v1/analyses/{analysis_id}/revise", response_model=AnalysisResponse)
async def revise_analysis(analysis_id: str, req: ReviseRequest):
    """Правка плана: обновить период/product_code → пересобрать план."""
    import re

    conn = _get_analyses_conn()
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")

    if row["status"] != "awaiting_approval":
        conn.close()
        raise HTTPException(status_code=400, detail=f"Анализ в статусе {row['status']}, нельзя revise")

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
    conn.close()

    return _row_to_response(row)


@app.post("/api/v1/analyses/{analysis_id}/reject", response_model=AnalysisResponse)
async def reject_analysis(analysis_id: str):
    """Отклонить план."""
    conn = _get_analyses_conn()
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Анализ {analysis_id} не найден")

    conn.execute("UPDATE analyses SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                 (analysis_id,))
    conn.commit()
    conn.close()

    return _row_to_response(row=None, analysis_id=analysis_id, status="rejected")


@app.post("/api/v1/reports/management")
async def management_report(background_tasks: BackgroundTasks):
    """Авто-отчёт: fixed workflow (топ-10 рост, топ-10 падение, критические остатки, отзывы).

    Запускает 4 анализа параллельно и собирает результаты.
    """
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
    conn.close()

    return {
        "report_id": report_id,
        "analysis_ids": analysis_ids,
        "status": "executing",
        "message": "Отчёт формируется. Результаты доступны через GET /api/v1/analyses/{id}",
    }


@app.get("/api/v1/health")
async def health():
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