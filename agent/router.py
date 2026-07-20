"""
agent/router.py — Router: классификация вопроса менеджера.

Определяет:
  - какой skill нужен (из 4 классов)
  - коды товаров в вопросе
  - период анализа в днях

Использует OpenAI API (gpt-4o-mini) с structured output.
Fallback: keyword-классификация без LLM.

Запуск:
    python -m agent.router "Почему упали продажи ЦБ-00007397?"
"""

import os
import re
import sys
import json
from dotenv import load_dotenv

from agent.schemas import SkillType, RoutingResult

# .env — переменная token (OpenAI API key)
load_dotenv()

# === Конфигурация LLM ===
MODEL_NAME = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
API_KEY = os.getenv("token", "")

# === System Prompt ===

SYSTEM_PROMPT = """Ты — маршрутизатор аналитического ассистента Mirrolla.

Твоя задача: по вопросу менеджера определить:
1. skill — какой аналитический модуль нужен
2. product_codes — коды товаров (формат ЦБ-XXXXXXXX или ФР-XXXXXXXX), если упомянуты
3. period_days — период анализа в днях

## Доступные skills:

1. **sales-decline-analysis** — анализ причин падения продаж товара.
   Ключевые слова: упали, снизились, падение, почему упали, просадка, хуже, меньше продаж.

2. **inventory-planning** — остатки, склад, план производства.
   Ключевые слова: заканчивается, остатки, склад, заказать, производство, произвести, дозаказать, запас, критические остатки.

3. **portfolio-growth** — рост/падение портфеля, сравнение с рынком/категорией.
   Ключевые слова: растёт, растёт быстрее, топ растущих, топ падающих, динамика, рынок, категория, лидеры роста.

4. **reviews-and-pricing** — отзывы, жалобы, цены.
   Ключевые слова: отзывы, плохие отзывы, жалобы, негативные, рейтинг, цена, изменить цену, ценовой эксперимент.

## Few-shot примеры:

Вопрос: "Почему упали продажи шампуня с кератином?"
→ skill: sales-decline-analysis, product_codes: [], period_days: 14

Вопрос: "Почему снизились продажи ЦБ-00007397?"
→ skill: sales-decline-analysis, product_codes: ["ЦБ-00007397"], period_days: 14

Вопрос: "Что заканчивается на складе?"
→ skill: inventory-planning, product_codes: [], period_days: 7

Вопрос: "Что растёт быстрее рынка?"
→ skill: portfolio-growth, product_codes: [], period_days: 14

Вопрос: "Какие отзывы плохие?"
→ skill: reviews-and-pricing, product_codes: [], period_days: 30

Вопрос: "Закажи производство репейного масла"
→ skill: inventory-planning, product_codes: [], period_days: 14

Вопрос: "Какие товары требуют изменения цены?"
→ skill: reviews-and-pricing, product_codes: [], period_days: 30

Вопрос: "Что нужно заказать в производство за последний месяц?"
→ skill: inventory-planning, product_codes: [], period_days: 30

## Правила:
- Если в вопросе есть код товара (ЦБ-XXXXXXXX или ФР-XXXXXXXX) — извлекай его в product_codes.
- Если кодов нет — product_codes = [] (пустой массив).
- "за последний месяц" → period_days: 30, "за неделю" → 7, "за две недели" → 14.
- Если период не указан — period_days: 14.
- Классифицируй строго по 4 skill-классам, ничего не выдумывай.
"""

# === Regex для извлечения кодов товаров ===
# Коды товаров: ЦБ-XXXXXXXX (Косметика/БАД) или ФР-XXXXXXXX (Фармация)
# ВАЖНО: ЦБ (буквы Б), НЕ ЦР (буква Р). Regex (ЦБ|ФР)-\d{8}
CODE_PATTERN = re.compile(r"(?:ЦБ|ФР)-\d{8}")

# === Keyword fallback ===

KEYWORD_MAP: dict[SkillType, list[str]] = {
    SkillType.SALES_DECLINE: ["упал", "сниз", "падени", "просадк", "хуже", "меньше продаж"],
    SkillType.INVENTORY: ["заканчив", "остат", "склад", "заказать", "произв", "дозаказ", "запас", "критическ"],
    SkillType.PORTFOLIO_GROWTH: ["растёт", "растет", "быстрее", "топ растущ", "топ падающ", "динамик", "рынок", "категори", "лидер"],
    SkillType.REVIEWS_PRICING: ["отзыв", "плохие", "жалоб", "негативн", "рейтинг", "цен", "жалоб"],
}


def _keyword_fallback(text: str) -> RoutingResult:
    """
    Keyword-классификация без LLM.

    Используется если LLM недоступен или вернул ошибку.
    """
    text_lower = text.lower()

    # Считаем совпадения для каждого skill
    scores: dict[SkillType, int] = {s: 0 for s in SkillType}
    for skill, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in text_lower:
                scores[skill] += 1

    # Выбираем skill с максимальным счётом
    best_skill = max(scores, key=lambda s: scores[s])

    # Если ничего не совпало — дефолт на sales-decline
    if scores[best_skill] == 0:
        best_skill = SkillType.SALES_DECLINE

    # Извлекаем коды товаров
    codes = CODE_PATTERN.findall(text)

    # Определяем период
    period = _extract_period(text)

    return RoutingResult(
        skill=best_skill,
        product_codes=codes,
        period_days=period,
    )


def _extract_period(text: str) -> int:
    """Извлечь период в днях из текста вопроса."""
    text_lower = text.lower()
    if "месяц" in text_lower:
        return 30
    if "две недел" in text_lower or "2 недел" in text_lower:
        return 14
    if "недел" in text_lower:
        return 7
    return 14  # дефолт


def route_sync(text: str) -> RoutingResult:
    """Синхронная обёртка для CLI и API.

    Безопасна для вызова из async event loop (FastAPI) —
    вызывает sync-путь напрямую, без event loop манипуляций.
    """
    return _route_sync_impl(text)


def _route_sync_impl(text: str) -> RoutingResult:
    """Синхронная маршрутизация — работает в любом контексте."""
    if not API_KEY:
        print("  [Router] ⚠ API ключ не найден, использую keyword-fallback")
        return _keyword_fallback(text)

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=MODEL_NAME,
            api_key=API_KEY,
            temperature=0,
        )
        structured_llm = llm.with_structured_output(RoutingResult)
        result = structured_llm.invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ]
        )
        return result

    except Exception as e:
        print(f"  [Router] ⚠ LLM ошибся: {e}")
        print("  [Router] → fallback на keyword-классификацию")
        return _keyword_fallback(text)


# === CLI ===

def main():
    if len(sys.argv) < 2:
        print("Использование: python -m agent.router \"Вопрос менеджера\"")
        print()
        print("Примеры:")
        print('  python -m agent.router "Почему упали продажи ЦБ-00007397?"')
        print('  python -m agent.router "Что заканчивается на складе?"')
        print('  python -m agent.router "Какие отзывы плохие?"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"Вопрос: {question}")
    print()

    result = route_sync(question)

    print("Результат маршрутизации:")
    print(json.dumps(
        {
            "skill": result.skill.value,
            "product_codes": result.product_codes,
            "period_days": result.period_days,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()