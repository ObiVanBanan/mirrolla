"""Diagnostic: показать сырой message text от Code Interpreter.

Запускает CI на вопросе и печатает:
1. Полный text из message (output_text) — без парсинга
2. Сколько code_interpreter_call было (сколько раз CI выполнял код)
3. Какие файлы (PNG/CSV/JSON) CI вернул

Запуск:
    PYTHONPATH= PYTHONHOME= ./venv/Scripts/python.exe tools/ci_raw_text.py "вопрос"
"""
import os
import sys

# Setup project path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

from agent.planner import plan as generate_plan
from agent.executor import _collect_data_files, _prefetch_balances, _build_prompt
from agent.ci_runner import CIRunner


def main():
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "какие товары заканчиваются?"

    print(f"\n{'='*70}")
    print(f"  ДИАГНОСТИКА: сырой text от Code Interpreter")
    print(f"{'='*70}")
    print(f"Вопрос: {question}\n")

    # Шаг 1: Plan
    print("--- Planner ---")
    analysis_plan = generate_plan(question)
    print(f"Skill: {analysis_plan.skill.value}")
    print(f"Гипотез: {len(analysis_plan.hypotheses)}")

    # Шаг 2: Pre-fetch balances + collect files
    print("\n--- Pre-fetch + files ---")
    balances_ok, balances_msg = _prefetch_balances(analysis_plan)
    print(f"Балансы: {balances_msg}")
    file_paths = _collect_data_files(analysis_plan)
    print(f"Файлов: {len(file_paths)}")

    # Шаг 3: Prompt — но БЕЗ требования JSON, просто «проанализируй и ответь»
    # Используем стандартный prompt, но посмотрим raw output
    prompt = _build_prompt(analysis_plan, balances_ok)

    # Шаг 4: Run CI
    print("\n--- Code Interpreter ---")
    runner = CIRunner()
    ci_result = runner.run_analysis(prompt=prompt, file_paths=file_paths, max_retries=1)

    print(f"\n{'='*70}")
    print(f"  СЫРОЙ TEXT ОТ CI (message output_text, без парсинга)")
    print(f"{'='*70}")
    print(ci_result.get("text", "(пусто)"))
    print(f"\n{'='*70}")
    print(f"  МЕТА")
    print(f"{'='*70}")
    print(f"status: {ci_result.get('status')}")
    print(f"text length: {len(ci_result.get('text', ''))} символов")
    print(f"charts: {ci_result.get('charts', [])}")
    print(f"error: {ci_result.get('error', '')}")


if __name__ == "__main__":
    main()