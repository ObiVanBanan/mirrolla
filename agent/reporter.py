"""
agent/reporter.py — Reporter LLM: интерпретация findings в ответ менеджеру.

Двухфазная модель:
- Code Interpreter возвращает структурированные findings (фактура)
- Reporter LLM берёт findings + question + skill и формирует человекочитаемый ответ

Использует gpt-4o (лучше пишет) отдельно от CI (gpt-4o-mini).
"""

import os
import json
from dotenv import load_dotenv

from agent.schemas import Finding, SkillType

load_dotenv()

MODEL_NAME = os.getenv("REPORTER_MODEL", "gpt-4o")
API_KEY = os.getenv("token", "")


REPORTER_PROMPT = """Ты — бизнес-аналитик маркетплейсов Mirrolla.

Ответь на исходный вопрос менеджера, используя только предоставленный
JSON анализа (findings). Не придумывай данные, которых нет в findings.

## Правила ответа:

1. Сначала дай прямой ответ в 1-3 предложениях (сколько товаров, главная проблема).
2. Затем перечисли наиболее важные findings (топ-5 по приоритету).
3. Для каждого объекта назови:
   - артикул (entity_id) или ID;
   - название (name);
   - конкретную причину (из reasons, с цифрами);
   - основные показатели (из metrics);
   - рекомендуемое действие (recommended_action).
4. Не придумывай отсутствующие данные.
5. Не пересказывай технические подробности Python/JSON.
6. Если answer_status не "answered", объясни, каких данных не хватает.
7. Формат — markdown: заголовок, краткий итог, нумерованный список товаров.
8. Все тексты на русском языке.

## Пример ответа:

### Заканчиваются 14 товаров

У 5 товаров запас менее чем на 3 дня, ещё 9 закончатся в течение недели.
Срочно нужно пополнить 3 товара.

**Критичные (заказать сегодня):**

1. **ЦБ-00048374** — Шампунь против перхоти с кетоконазолом, 500мл
   - Остаток: 0 шт, продажи за 7 дней: 23 шт
   - → Заказать 69 шт на горизонт 21 день

2. **ЦБ-00049469** — Гель-бальзам для ног, 75 мл (2024)
   - Остаток: 0 шт, продажи за 7 дней: 27 шт
   - → Заказать 81 шт на горизонт 21 день
"""


def synthesize(
    question: str,
    skill: SkillType,
    findings: list[Finding],
    limitations: list[str],
    answer_status: str = "answered",
    ci_answer: str = "",
) -> str:
    """
    Сформировать человекочитаемый ответ менеджеру на основе findings.

    Args:
        question: исходный вопрос менеджера.
        skill: использованный skill.
        findings: список конкретных объектов от CI.
        limitations: ограничения анализа.
        answer_status: answered / partial / not_enough_data.
        ci_answer: короткий ответ из CI (если есть).

    Returns:
        str: markdown-ответ для менеджера.
    """
    if not API_KEY:
        # Fallback — простой шаблон без LLM
        return _fallback_synthesize(question, skill, findings, limitations, answer_status, ci_answer)

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=MODEL_NAME,
            api_key=API_KEY,
            temperature=0.2,
        )

        # Подготовить findings для LLM
        findings_data = {
            "question": question,
            "skill": skill.value,
            "answer_status": answer_status,
            "findings": [f.model_dump() for f in findings],
            "limitations": limitations,
            "ci_answer": ci_answer,
        }

        response = llm.invoke([
            {"role": "system", "content": REPORTER_PROMPT},
            {"role": "user", "content": json.dumps(findings_data, ensure_ascii=False, default=str)},
        ])

        return response.content

    except Exception as e:
        print(f"  [Reporter] ⚠ LLM error: {e}")
        return _fallback_synthesize(question, skill, findings, limitations, answer_status, ci_answer)


def _fallback_synthesize(
    question: str,
    skill: SkillType,
    findings: list[Finding],
    limitations: list[str],
    answer_status: str,
    ci_answer: str,
) -> str:
    """Простой шаблонный ответ без LLM."""
    if not findings:
        if ci_answer:
            return ci_answer
        return f"Не удалось сформировать ответ. Статус: {answer_status}."

    lines = [f"### Ответ на вопрос: {question}\n"]

    if answer_status != "answered":
        lines.append(f"⚠ Статус: {answer_status}\n")

    lines.append(f"Найдено объектов: {len(findings)}\n")

    # Топ-5 по приоритету
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(findings, key=lambda f: priority_order.get(f.priority, 4))

    lines.append("**Топ объектов:**\n")
    for i, f in enumerate(sorted_findings[:5], 1):
        lines.append(f"{i}. **{f.entity_id}** — {f.name}")
        for r in f.reasons[:2]:
            lines.append(f"   - {r}")
        if f.recommended_action:
            lines.append(f"   - → {f.recommended_action}")

    if limitations:
        lines.append("\n**Ограничения:**")
        for l in limitations[:3]:
            lines.append(f"- {l}")

    return "\n".join(lines)