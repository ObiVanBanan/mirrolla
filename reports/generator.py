"""
reports/generator.py — Авто-отчёт менеджера (fixed workflow).

Запускает 4 анализа параллельно и собирает результаты:
1. Топ-10 растущих товаров (portfolio-growth)
2. Топ-10 падающих товаров (portfolio-growth, вопрос с "падающ")
3. Критические остатки (inventory-planning)
4. Негативные отзывы (reviews-and-pricing)

Использование:
    # Через API (когда сервер запущен)
    python -m reports.generator

    # Или напрямую через agent (без API)
    python -m reports.generator --direct
"""

import os
import sys
import json
import time
import asyncio
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("MIRROLLA_API", "http://127.0.0.1:8000/api/v1")

# === Fixed workflow: 4 анализа ===

QUESTIONS = [
    ("Топ-10 растущих товаров", "growth"),
    ("Топ-10 падающих товаров", "decline"),
    ("Какие товары заканчиваются на складе?", "critical_stock"),
    ("Какие отзывы требуют реакции менеджера?", "bad_reviews"),
]


def _create_and_wait(question: str, timeout_s: int = 300, poll_s: int = 3) -> dict:
    """
    Создать анализ через API, дождаться завершения, вернуть результат.
    """
    # 1. Create
    r = requests.post(f"{API_BASE}/analyses", json={"question": question}, timeout=30)
    r.raise_for_status()
    analysis_id = r.json()["id"]
    print(f"  [created] {analysis_id[:8]} | {question[:50]}")

    # 2. Approve
    r = requests.post(f"{API_BASE}/analyses/{analysis_id}/approve", timeout=10)
    r.raise_for_status()

    # 3. Poll until done
    elapsed = 0
    while elapsed < timeout_s:
        time.sleep(poll_s)
        elapsed += poll_s
        r = requests.get(f"{API_BASE}/analyses/{analysis_id}", timeout=10)
        r.raise_for_status()
        data = r.json()
        if data["status"] in ("done", "error", "rejected"):
            print(f"  [{data['status']}] {analysis_id[:8]} | findings={len(data.get('result',{}).get('findings',[])) if data.get('result') else 0}")
            return data

    print(f"  [timeout] {analysis_id[:8]}")
    return {"id": analysis_id, "status": "timeout", "question": question}


def generate_report_via_api() -> dict:
    """
    Сгенерировать авто-отчёт через API.

    Returns:
        dict: {section_name: analysis_result}
    """
    print(f"\n{'='*60}")
    print(f"  АВТО-ОТЧЁТ MIRROLLA")
    print(f"  API: {API_BASE}")
    print(f"{'='*60}\n")

    # Health check
    try:
        r = requests.get(f"{API_BASE.replace('/api/v1', '')}/api/v1/health", timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"❌ API недоступен: {e}")
        print("   Запустите: PYTHONPATH= PYTHONHOME= ./venv/Scripts/python.exe -m uvicorn api.main:app --port 8000")
        sys.exit(1)

    # Run 4 analyses sequentially (CI sandbox is single-tenant, parallel не поможет)
    results = {}
    for question, section in QUESTIONS:
        print(f"\n[{section}] {question}")
        try:
            results[section] = _create_and_wait(question)
        except Exception as e:
            print(f"  [error] {e}")
            results[section] = {"error": str(e), "question": question}

    return results


def render_markdown_report(results: dict) -> str:
    """Собрать markdown-отчёт из результатов."""
    md = ["# Авто-отчёт Mirrolla\n"]
    md.append(f"_Сгенерирован: {time.strftime('%Y-%m-%d %H:%M')}_\n")

    for section, label in [("growth", "📈 Топ-10 растущих"),
                           ("decline", "📉 Топ-10 падающих"),
                           ("critical_stock", "🔴 Критические остатки"),
                           ("bad_reviews", "⚠️ Негативные отзывы")]:
        md.append(f"\n## {label}\n")
        data = results.get(section, {})
        if "error" in data:
            md.append(f"❌ Ошибка: {data['error']}\n")
            continue
        if data.get("status") != "done":
            md.append(f"⚠️ Статус: {data.get('status', 'unknown')}\n")
            continue
        result = data.get("result", {})
        if result and result.get("summary"):
            md.append(result["summary"])
            md.append("")
        if result and result.get("limitations"):
            md.append("\n**Ограничения:**")
            for l in result["limitations"]:
                md.append(f"- {l}")

    return "\n".join(md)


def main():
    """Entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Mirrolla авто-отчёт")
    parser.add_argument("--direct", action="store_true", help="Запустить через agent напрямую (без API)")
    parser.add_argument("--output", "-o", default=None, help="Сохранить в файл (markdown)")
    args = parser.parse_args()

    if args.direct:
        print("Режим --direct пока не реализован. Используйте API:")
        print("  1. uvicorn api.main:app --port 8000")
        print("  2. python -m reports.generator")
        sys.exit(1)

    results = generate_report_via_api()
    report_md = render_markdown_report(results)

    # Output
    print(f"\n{'='*60}")
    print(f"  ОТЧЁТ (markdown)")
    print(f"{'='*60}\n")
    print(report_md[:2000])
    if len(report_md) > 2000:
        print(f"\n... ({len(report_md)} chars total)")

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"\n📄 Сохранено: {args.output}")


if __name__ == "__main__":
    main()