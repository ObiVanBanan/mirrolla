"""
Router for Mirrolla analyses.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Sequence

from dotenv import load_dotenv

from agent.schemas import AnalysisMode, RoutingResult, SkillType
from application.datasets.execution import (
    ResolvedDatasetInput,
    serialize_untrusted_dataset_context,
)

load_dotenv()

MODEL_NAME = os.getenv("ROUTER_MODEL", "gpt-4o-mini")
API_KEY = os.getenv("token", "")

SYSTEM_PROMPT = """Ты определяешь, нужен ли вопросу специализированный skill.

Выбирай specialized только тогда, когда намерение пользователя явно соответствует одному
из доступных skills. Для обычных операций над приложенным CSV, XLSX или JSON выбирай general.

Правила:
- В general analysis_mode = "general", skill = null.
- В specialized analysis_mode = "specialized", skill должен быть одним из доступных skills.
- Не выбирай skill только потому, что система ожидает непустое значение.
- Не считай любой числовой датасет анализом продаж.
- Профиль датасета помогает понять структуру данных, но skill выбирается по намерению пользователя.

Примеры general:
{"question":"Сколько строк в mapping_results.csv?","analysis_mode":"general","skill":null}
{"question":"Покажи записи, где status не равен mapped","analysis_mode":"general","skill":null}
{"question":"Найди дубликаты и пропуски","analysis_mode":"general","skill":null}

Примеры specialized:
{"question":"Почему упали продажи артикула 123?","analysis_mode":"specialized","skill":"sales-decline-analysis"}
{"question":"Какие товары скоро закончатся и что заказать?","analysis_mode":"specialized","skill":"inventory-planning"}
"""

CODE_PATTERN = re.compile(r"(?:ЦБ|ФР)-\d{8}")

KEYWORD_MAP: dict[SkillType, list[str]] = {
    SkillType.SALES_DECLINE: ["упал", "сниз", "падени", "просадк", "хуже", "меньше продаж"],
    SkillType.INVENTORY: ["заканчив", "остат", "склад", "заказать", "произв", "дозаказ", "запас", "критическ"],
    SkillType.PORTFOLIO_GROWTH: ["растёт", "растет", "быстрее", "топ растущ", "топ падающ", "динамик", "рынок", "категори", "лидер"],
    SkillType.REVIEWS_PRICING: ["отзыв", "плохие", "жалоб", "негативн", "рейтинг", "цен", "цена"],
}


def _extract_period(text: str) -> int:
    text_lower = text.lower()
    if "месяц" in text_lower:
        return 30
    if "две недел" in text_lower or "2 недел" in text_lower:
        return 14
    if "недел" in text_lower:
        return 7
    return 14


def _build_dataset_context_block(dataset_context: Sequence[ResolvedDatasetInput] | None) -> str:
    if not dataset_context:
        return ""
    return (
        "\n\n## Attached dataset profiles\n"
        "Используй это только как контекст структуры данных.\n"
        "Отсутствие специализированного skill не является ошибкой.\n\n"
        f"{serialize_untrusted_dataset_context(dataset_context)}"
    )


def _keyword_fallback(
    text: str,
    dataset_context: Sequence[ResolvedDatasetInput] | None = None,
) -> RoutingResult:
    del dataset_context
    text_lower = text.lower()
    scores: dict[SkillType, int] = {skill: 0 for skill in SkillType}
    for skill, keywords in KEYWORD_MAP.items():
        for keyword in keywords:
            if keyword in text_lower:
                scores[skill] += 1

    best_skill = max(scores, key=lambda skill: scores[skill])
    best_score = scores[best_skill]
    codes = CODE_PATTERN.findall(text)
    period = _extract_period(text)

    if best_score <= 0:
        return RoutingResult(
            analysis_mode=AnalysisMode.GENERAL,
            skill=None,
            skill_confidence=0.0,
            product_codes=codes,
            period_days=period,
        )

    confidence = min(1.0, 0.35 + 0.2 * best_score)
    return RoutingResult(
        analysis_mode=AnalysisMode.SPECIALIZED,
        skill=best_skill,
        skill_confidence=confidence,
        product_codes=codes,
        period_days=period,
    )


def route_sync(
    text: str,
    dataset_context: Sequence[ResolvedDatasetInput] | None = None,
) -> RoutingResult:
    return _route_sync_impl(text, dataset_context=dataset_context)


def _route_sync_impl(
    text: str,
    dataset_context: Sequence[ResolvedDatasetInput] | None = None,
) -> RoutingResult:
    if not API_KEY:
        print("  [Router] API key not found, using keyword fallback")
        return _keyword_fallback(text, dataset_context=dataset_context)

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
                {"role": "system", "content": SYSTEM_PROMPT + _build_dataset_context_block(dataset_context)},
                {"role": "user", "content": text},
            ]
        )
        return result
    except Exception as exc:
        print(f"  [Router] LLM error: {exc}")
        print("  [Router] -> fallback to keyword routing")
        return _keyword_fallback(text, dataset_context=dataset_context)


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m agent.router "Question"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    result = route_sync(question)
    print(
        json.dumps(
            {
                "analysis_mode": result.analysis_mode.value,
                "skill": result.skill.value if result.skill is not None else None,
                "skill_confidence": result.skill_confidence,
                "product_codes": result.product_codes,
                "period_days": result.period_days,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
