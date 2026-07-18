"""
agent/nodes.py — Узлы LangGraph StateGraph для M5 HITL.

Каждый узел — функция, принимающая AgentState, возвращающая dict обновлений state.
Граф: understand → route → plan → [interrupt] → execute → report → END

Запуск:
    python -m agent "Почему упали продажи ЦБ-00007397?"
"""

import os
import sys
import json
import uuid
from typing import TypedDict, Optional

from dotenv import load_dotenv

from agent.schemas import (
    SkillType,
    RoutingResult,
    AnalysisPlan,
    ExecutionResult,
    Finding,
)
from agent.router import route_sync
from agent.planner import plan as generate_plan
from agent.executor import execute as execute_plan
from agent.reporter import synthesize as reporter_synthesize

load_dotenv()


# === Agent State ===

class AgentState(TypedDict, total=False):
    """Состояние графа — сохраняется в SQLite checkpointer между запусками.

    Поля:
    - thread_id: UUID анализа (= checkpoint thread_id)
    - question: исходный вопрос менеджера
    - routing: результат Router (skill, product_codes, period_days)
    - plan: план анализа (гипотезы, датасеты, метод)
    - approval: ответ менеджера ("approve" | "revise" | "reject" | None)
    - revision_feedback: текст правки от менеджера (при revise)
    - result: результат выполнения (findings, summary, charts)
    - error: сообщение об ошибке (если есть)
    - status: текущий статус ("planning" | "awaiting_approval" | "executing" | "done" | "rejected" | "error")
    """
    thread_id: str
    question: str
    routing: RoutingResult
    plan: AnalysisPlan
    approval: Optional[str]
    revision_feedback: Optional[str]
    result: ExecutionResult
    error: Optional[str]
    status: str


# === Узлы графа ===

def understand_node(state: AgentState) -> dict:
    """Узел 1: понять вопрос, инициализировать thread_id."""
    question = state.get("question", "")
    if not question:
        return {"error": "Вопрос не передан", "status": "error"}

    thread_id = state.get("thread_id") or str(uuid.uuid4())
    print(f"\n{'='*60}")
    print(f"  АНАЛИЗ #{thread_id[:8]}")
    print(f"{'='*60}")
    print(f"📋 Вопрос: {question}")

    return {"thread_id": thread_id, "status": "planning"}


def route_node(state: AgentState) -> dict:
    """Узел 2: маршрутизация вопроса → skill + product_codes + period_days."""
    question = state.get("question", "")
    print(f"\n--- Шаг 1: Router ---")

    routing = route_sync(question)
    print(f"  Skill: {routing.skill.value}")
    print(f"  Коды: {routing.product_codes}")
    print(f"  Период: {routing.period_days} дней")

    return {"routing": routing}


def plan_node(state: AgentState) -> dict:
    """Узел 3: формирование плана анализа."""
    question = state.get("question", "")
    routing = state.get("routing")
    print(f"\n--- Шаг 2: Planner ---")

    analysis_plan = generate_plan(question, routing=routing)
    print(f"  Гипотез: {len(analysis_plan.hypotheses)}")
    print(f"  Ограничений: {len(analysis_plan.limitations)}")

    # Показать план менеджеру
    print(f"\n{'='*60}")
    print(f"  ПЛАН АНАЛИЗА")
    print(f"{'='*60}")
    print(f"🎯 Skill: {analysis_plan.skill.value}")
    print(f"📅 Период: {analysis_plan.period.current_days} дней")
    print(f"📦 Коды товаров: {', '.join(analysis_plan.product_codes) or 'весь портфель'}")
    print(f"\n📊 Гипотезы:")
    for h in analysis_plan.hypotheses:
        print(f"  {h.id}: {h.title}")
        print(f"     Датасеты: {', '.join(h.datasets)}")
        print(f"     Метод: {h.method[:100]}")
    if analysis_plan.limitations:
        print(f"\n⚠ Ограничения:")
        for l in analysis_plan.limitations:
            print(f"  - {l}")

    return {"plan": analysis_plan, "status": "awaiting_approval"}


def execute_node(state: AgentState) -> dict:
    """Узел 4: выполнение плана анализа через Executor + Reporter."""
    plan = state.get("plan")
    if not plan:
        return {"error": "План не сформирован", "status": "error"}

    print(f"\n--- Шаг 3: Executor ---")

    try:
        result = execute_plan(plan)
        print(f"\n--- Шаг 4: Reporter ---")
        print(f"  ✅ Готово")
        return {"result": result, "status": "done"}
    except Exception as e:
        print(f"  ❌ Ошибка выполнения: {e}")
        return {"error": str(e), "status": "error"}


def report_node(state: AgentState) -> dict:
    """Узел 5: вывод финального ответа менеджеру.

    Reporter LLM уже вызван внутри execute_node (executor.py Шаг 6),
    поэтому здесь только форматированный вывод.
    """
    result = state.get("result")
    if not result:
        return {"status": "error", "error": "Нет результата для отчёта"}

    print(f"\n{'='*60}")
    print(f"  ОТВЕТ МЕНЕДЖЕРУ")
    print(f"{'='*60}")
    print(f"\n{result.summary}")

    if result.findings:
        print(f"\n{'='*60}")
        print(f"  СТРУКТУРИРОВАННЫЕ FINDINGS ({len(result.findings)})")
        print(f"{'='*60}")
        for f in result.findings:
            priority_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(f.priority, "⚪")
            print(f"\n  {priority_icon} [{f.priority}] {f.entity_id} — {f.name}")
            for r in f.reasons:
                print(f"       • {r}")
            if f.metrics:
                print(f"       metrics: {json.dumps(f.metrics, ensure_ascii=False, default=str)[:200]}")
            if f.recommended_action:
                print(f"       → {f.recommended_action}")

    if result.charts:
        print(f"\n📊 Графики:")
        for c in result.charts:
            print(f"  → {c}")

    if result.limitations:
        print(f"\n⚠ Ограничения:")
        for l in result.limitations:
            print(f"  - {l}")

    print(f"\n{'='*60}")
    return {"status": "done"}


def reject_node(state: AgentState) -> dict:
    """Узел: отмена анализа менеджером."""
    print(f"\n{'='*60}")
    print(f"  АНАЛИЗ ОТМЕНЁН")
    print(f"{'='*60}")
    print(f"Менеджер отклонил план анализа.")
    return {"status": "rejected"}