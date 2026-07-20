"""
agent/graph.py — LangGraph StateGraph для M5 HITL (человек в цикле).

Граф: understand → route → plan → [interrupt] → execute → report → END
                                          ↓
                                     (approve → execute)
                                     (revise → plan)
                                     (reject → reject → END)

SQLite checkpointer сохраняет состояние между запусками:
- менеджер запускает анализ → план → сервис останавливается (interrupt)
- менеджер закрывает терминал
- на следующий день: `python -m agent --resume <thread_id> approve`
- сервис восстанавливает состояние из checkpoint → выполняет → ответ

Запуск:
    # Новый анализ
    python -m agent "Почему упали продажи ЦБ-00007397?"

    # Подтвердить (после interrupt)
    python -m agent --resume <thread_id> approve

    # Отклонить
    python -m agent --resume <thread_id> reject

    # Правка
    python -m agent --resume <thread_id> revise "период 30 дней, товар ЦБ-00049405"

    # Список сохранённых анализов
    python -m agent --list
"""

import os
import sys
import json
import sqlite3
import uuid
from typing import Optional

from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command
from langgraph.errors import GraphInterrupt

from agent.nodes import (
    AgentState,
    understand_node,
    route_node,
    plan_node,
    execute_node,
    report_node,
    reject_node,
)

load_dotenv()

# === Конфигурация ===

CHECKPOINT_DB = os.path.join("data", "checkpoints.sqlite")


def _get_connection():
    """Получить SQLite connection для checkpointer."""
    os.makedirs(os.path.dirname(CHECKPOINT_DB), exist_ok=True)
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# === Узел interrupt (HITL) ===

def human_approval_node(state: AgentState) -> dict:
    """Узел: остановка и ожидание подтверждения менеджера.

    В режиме CLI (первый запуск) — печатает prompt и ждёт ввод.
    В режиме resume (--resume <thread_id>) — берёт approval из state.
    """
    if state.get("approval"):
        # Approval уже установлен (через --resume) → пропускаем interrupt
        return {}

    # Прерывание: LangGraph сохраняет state в checkpointer
    # При resume — approval будет в state
    print(f"\n{'='*60}")
    print(f"  ОЖИДАНИЕ ПОДТВЕРЖДЕНИЯ")
    print(f"{'='*60}")
    print(f"  Thread ID: {state.get('thread_id', '?')}")
    print(f"\n  Для подтверждения:")
    print(f'    python -m agent --resume {state.get("thread_id", "?")} approve')
    print(f"  Для правки:")
    print(f'    python -m agent --resume {state.get("thread_id", "?")} revise "период 30 дней"')
    print(f"  Для отмены:")
    print(f'    python -m agent --resume {state.get("thread_id", "?")} reject')

    # interrupt() сохраняет state и выходит
    approval = interrupt({
        "prompt": "approve / revise / reject?",
        "thread_id": state.get("thread_id"),
    })

    return {"approval": approval}


def revision_node(state: AgentState) -> dict:
    """Узел: обработка правки менеджера — пересборка плана."""
    feedback = state.get("revision_feedback", "")
    print(f"\n--- Правка плана: {feedback} ---")

    routing = state.get("routing")
    question = state.get("question", "")

    # Парсинг feedback → обновление routing
    import re
    updates = {}

    # Период: "период 30 дней" → period_days=30
    period_match = re.search(r"период\s*(\d+)", feedback.lower())
    if period_match:
        new_period = int(period_match.group(1))
        updates["period_days"] = new_period
        print(f"  Период обновлён: {new_period} дней")

    # Коды товаров: "товар ЦБ-00049405" → product_codes=["ЦБ-00049405"]
    # Коды начинаются с ЦБ или ФР (не ЦР!), regex: (ЦБ|ФР)-\d{8}
    code_match = re.findall(r"(?:ЦБ|ФР)-\d{8}", feedback)
    if code_match:
        updates["product_codes"] = code_match
        print(f"  Коды товаров обновлены: {code_match}")

    # Применить все обновления за один раз (model_copy chaining ломает — каждый
    # новый объект теряет предыдущие обновления если основан на оригинале)
    if updates:
        routing = routing.model_copy(update=updates)

    # Сброс approval (для следующего interrupt)
    return {"routing": routing, "approval": None, "status": "awaiting_approval"}


# === Сборка графа ===

def build_graph(checkpointer=None):
    """Собрать StateGraph с HITL interrupt.

    Args:
        checkpointer: SqliteSaver или MemorySaver. Если None — MemorySaver (demo).

    Returns:
        Compiled graph, готовый к invoke.
    """
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()

    graph = StateGraph(AgentState)

    # Узлы
    graph.add_node("understand", understand_node)
    graph.add_node("route", route_node)
    graph.add_node("plan", plan_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("revision", revision_node)
    graph.add_node("execute", execute_node)
    graph.add_node("report", report_node)
    graph.add_node("reject", reject_node)

    # Рёбра
    graph.set_entry_point("understand")
    graph.add_edge("understand", "route")
    graph.add_edge("route", "plan")
    graph.add_edge("plan", "human_approval")

    # Условное ребро после human_approval
    def after_approval(state: AgentState) -> str:
        approval = state.get("approval", "")
        if approval == "approve":
            return "execute"
        elif approval == "revise":
            return "revision"
        elif approval == "reject":
            return "reject"
        return "execute"  # default

    graph.add_conditional_edges(
        "human_approval",
        after_approval,
        {"execute": "execute", "revision": "revision", "reject": "reject"},
    )

    # revision → plan (пересборка плана) → снова interrupt
    graph.add_edge("revision", "plan")

    # execute → report → END
    graph.add_edge("execute", "report")
    graph.add_edge("report", END)

    # reject → END
    graph.add_edge("reject", END)

    return graph.compile(checkpointer=checkpointer)


# === CLI ===

def _list_analyses(conn):
    """Показать список сохранённых анализов из checkpointer."""
    cursor = conn.cursor()
    # SqliteSaver хранит state в таблице checkpoint
    try:
        cursor.execute("SELECT DISTINCT thread_id FROM checkpoint ORDER BY thread_id DESC LIMIT 20")
        rows = cursor.fetchall()
        print(f"\n{'='*60}")
        print(f"  СОХРАНЁННЫЕ АНАЛИЗЫ ({len(rows)})")
        print(f"{'='*60}")
        for row in rows:
            thread_id = row[0]
            print(f"  {thread_id}")
        print(f"\nДля resume: python -m agent --resume <thread_id> approve")
    except Exception as e:
        print(f"  Не удалось получить список: {e}")


def main():
    """CLI entry point."""
    args = sys.argv[1:]

    if not args:
        print("Использование:")
        print('  python -m agent "Вопрос менеджера"')
        print("  python -m agent --resume <thread_id> approve|revise|reject")
        print("  python -m agent --list")
        sys.exit(1)

    # --list
    if args[0] == "--list":
        conn = _get_connection()
        _list_analyses(conn)
        conn.close()
        sys.exit(0)

    # --resume <thread_id> <action> [feedback]
    if args[0] == "--resume":
        if len(args) < 3:
            print("Использование: python -m agent --resume <thread_id> approve|revise|reject [feedback]")
            sys.exit(1)

        thread_id = args[1]
        action = args[2]
        feedback = " ".join(args[3:]) if len(args) > 3 else ""

        conn = _get_connection()
        checkpointer = SqliteSaver(conn=conn)

        # Восстановить state из checkpoint
        try:
            saved = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
        except Exception as e:
            print(f"Ошибка восстановления state: {e}")
            conn.close()
            sys.exit(1)

        if not saved:
            print(f"Анализ {thread_id} не найден в checkpoint")
            conn.close()
            sys.exit(1)

        # Обновить state с approval
        config = {"configurable": {"thread_id": thread_id}}
        app = build_graph(checkpointer)

        if action == "approve":
            app.invoke(Command(resume="approve"), config=config)
        elif action == "reject":
            app.invoke(Command(resume="reject"), config=config)
        elif action == "revise":
            # Сохранить feedback в state, затем resume
            # Сначала update state, потом resume
            current_state = saved.checkpoint.get("channel_values", {}) if saved.checkpoint else {}
            current_state["revision_feedback"] = feedback
            app.invoke(Command(resume="revise", update={"revision_feedback": feedback}), config=config)
        else:
            print(f"Неизвестное действие: {action}")
            conn.close()
            sys.exit(1)

        conn.close()
        sys.exit(0)

    # Новый анализ
    question = " ".join(args)
    conn = _get_connection()
    checkpointer = SqliteSaver(conn=conn)
    app = build_graph(checkpointer)

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n🆔 Thread ID: {thread_id}")
    print(f"   (сохраните для resume: python -m agent --resume {thread_id} approve)")

    try:
        app.invoke({"question": question, "thread_id": thread_id}, config=config)
    except GraphInterrupt:
        # interrupt — нормально, ждёт resume
        pass
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

    conn.close()


if __name__ == "__main__":
    main()