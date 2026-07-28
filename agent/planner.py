"""
Planner for Mirrolla analyses.
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

from application.datasets.execution import (
    ResolvedDatasetInput,
    serialize_untrusted_dataset_context,
)

from agent.router import route_sync
from agent.schemas import AnalysisPlan, Hypothesis, PeriodSpec, RoutingResult, SkillType

load_dotenv()

MODEL_NAME = os.getenv("PLANNER_MODEL", "gpt-4o")
API_KEY = os.getenv("token", "")
SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
PRODUCTS_PATH = os.path.join("data", "prepared", "products.json")

BASE_PROMPT = """Ты — планировщик аналитического анализа для Mirrolla.

Твоя задача: по вопросу менеджера, выбранному skill и периоду сформировать план анализа.

Главные правила:
- гипотезы должны соответствовать доступным данным;
- если прикреплены файлы, используй только их профили;
- не выдумывай отсутствующие датасеты, листы, колонки и строки;
- если данных не хватает, фиксируй это в limitations.
"""

LEGACY_DATASET_BLOCK = """## Доступные demo datasets
- sales
- stocks
- reviews_wb
- reviews_ozon
- categories
"""


def _load_skill_md(skill: SkillType) -> str:
    skill_path = os.path.join(SKILLS_DIR, skill.value, "SKILL.md")
    if not os.path.exists(skill_path):
        return ""
    with open(skill_path, "r", encoding="utf-8") as handle:
        return handle.read()


def _validate_product_codes(codes: list[str], *, allow_catalog_lookup: bool = True) -> list[str]:
    if not codes or not allow_catalog_lookup:
        return []

    warnings: list[str] = []
    try:
        with open(PRODUCTS_PATH, "r", encoding="utf-8") as handle:
            products = json.load(handle)
        existing_codes = {
            item["code"]
            for item in products
            if isinstance(item, dict) and "code" in item
        }
        for code in codes:
            if code not in existing_codes:
                warnings.append(f"Код товара {code} не найден в каталоге 1С (products.json)")
    except FileNotFoundError:
        warnings.append("Каталог products.json недоступен — валидация кодов пропущена")
    except Exception:
        warnings.append("Ошибка валидации кодов товаров")
    return warnings


def _build_dataset_context_block(dataset_context: list[ResolvedDatasetInput] | None) -> str:
    if not dataset_context:
        return ""
    return (
        "## Attached dataset profiles\n"
        "These are the factual datasets for the current analysis.\n"
        "Do not assume files, sheets, or columns that are not present below.\n"
        "Do not use raw dataset rows beyond these profile summaries.\n\n"
        f"{serialize_untrusted_dataset_context(dataset_context)}"
    )


def _build_messages(
    question: str,
    routing: RoutingResult,
    dataset_context: list[ResolvedDatasetInput] | None = None,
) -> list[dict]:
    skill_md = _load_skill_md(routing.skill)
    if dataset_context:
        system = (
            f"{BASE_PROMPT}\n\n"
            f"## Selected skill\n{routing.skill.value}\n\n"
            "## Attached planning mode\n"
            "Build the plan only from attached dataset profiles and the user question.\n"
            "Do not assume any hidden demo datasets, products catalog, or fixed time range.\n\n"
            f"{_build_dataset_context_block(dataset_context)}"
        )
    else:
        system = (
            f"{BASE_PROMPT}\n\n"
            f"## Selected skill\n{routing.skill.value}\n\n"
            f"## Skill instructions\n{skill_md}\n\n"
            f"{LEGACY_DATASET_BLOCK}"
        )

    user = "\n".join(
        [
            f"Вопрос менеджера: {question}",
            f"Skill: {routing.skill.value}",
            (
                f"Коды товаров: {', '.join(routing.product_codes)}"
                if routing.product_codes
                else "Коды товаров: не указаны"
            ),
            f"Период анализа: {routing.period_days} дней",
        ]
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_legacy_hypotheses(skill: SkillType) -> list[Hypothesis]:
    mapping: dict[SkillType, list[Hypothesis]] = {
        SkillType.SALES_DECLINE: [
            Hypothesis(
                id="H1",
                title="Дефицит остатков",
                datasets=["sales", "stocks"],
                method="Сопоставить продажи с остатками и проверить out-of-stock.",
                helpers=["compare_periods", "stockout_days"],
            ),
            Hypothesis(
                id="H2",
                title="Негативные отзывы",
                datasets=["reviews_wb", "reviews_ozon"],
                method="Проверить всплеск негативных отзывов и снижение рейтинга.",
                helpers=["negative_reviews_wb", "negative_reviews_ozon"],
            ),
            Hypothesis(
                id="H3",
                title="Динамика категории",
                datasets=["sales", "categories"],
                method="Сравнить динамику товара с его категорией.",
                helpers=["category_growth_by_type"],
            ),
            Hypothesis(
                id="H4",
                title="Общий тренд спроса",
                datasets=["sales"],
                method="Проверить тренд заказов и сезонный спад.",
                helpers=["daily_order_counts"],
            ),
        ],
        SkillType.INVENTORY: [
            Hypothesis(
                id="H1",
                title="Критические остатки",
                datasets=["sales", "stocks"],
                method="Оценить дни запаса и товары с риском stockout.",
                helpers=["critical_stocks"],
            )
        ],
        SkillType.PORTFOLIO_GROWTH: [
            Hypothesis(
                id="H1",
                title="Товары роста",
                datasets=["sales"],
                method="Сравнить продажи по периодам и найти товары роста.",
                helpers=["top_growth"],
            )
        ],
        SkillType.REVIEWS_PRICING: [
            Hypothesis(
                id="H1",
                title="Негативные отзывы",
                datasets=["reviews_wb", "reviews_ozon"],
                method="Собрать негативные отзывы и recurring complaints.",
                helpers=["negative_reviews_wb"],
            )
        ],
    }
    return mapping[skill]


def _fallback_attached_plan(
    question: str,
    routing: RoutingResult,
    extra_warnings: list[str],
    dataset_context: list[ResolvedDatasetInput],
) -> AnalysisPlan:
    hypotheses: list[Hypothesis] = []
    seen_temporal = False
    seen_numeric = False
    seen_entity = False

    for item in dataset_context:
        for sheet in item.profile.sheets:
            for column in sheet.columns:
                if column.inferred_type == "datetime":
                    seen_temporal = True
                if column.inferred_type in {"integer", "number"}:
                    seen_numeric = True
                lowered = column.name.lower()
                if "sku" in lowered or "product" in lowered or "name" in lowered:
                    seen_entity = True

    if seen_temporal and seen_numeric:
        hypotheses.append(
            Hypothesis(
                id="H1",
                title="Временная динамика метрик",
                datasets=["attached"],
                method="Проверить динамику доступных числовых показателей по временным полям.",
                helpers=[],
            )
        )
    if seen_entity and seen_numeric:
        hypotheses.append(
            Hypothesis(
                id="H2",
                title="Сравнение по сущностям",
                datasets=["attached"],
                method="Сопоставить числовые показатели между товарами или группами.",
                helpers=[],
            )
        )
    if seen_numeric:
        hypotheses.append(
            Hypothesis(
                id="H3",
                title="Аномалии в числовых полях",
                datasets=["attached"],
                method="Найти резкие отклонения и выбросы в доступных числовых полях.",
                helpers=[],
            )
        )
    if not hypotheses:
        hypotheses.append(
            Hypothesis(
                id="H1",
                title="Структурный обзор данных",
                datasets=["attached"],
                method="Проанализировать доступную структуру файлов и зафиксировать ограничения.",
                helpers=[],
            )
        )

    limitations = list(extra_warnings)
    limitations.append(
        "План построен только по профилям прикреплённых файлов. Отсутствующие датасеты и концепты не предполагаются."
    )

    return AnalysisPlan(
        skill=routing.skill,
        question=question,
        product_codes=routing.product_codes,
        period=PeriodSpec(current_days=routing.period_days, comparison="previous_equal_period"),
        hypotheses=hypotheses,
        limitations=limitations,
    )


def _fallback_plan(
    question: str,
    routing: RoutingResult,
    extra_warnings: list[str],
    dataset_context: list[ResolvedDatasetInput] | None = None,
) -> AnalysisPlan:
    if dataset_context:
        return _fallback_attached_plan(question, routing, extra_warnings, dataset_context)

    limitations = list(extra_warnings)
    if routing.period_days > 92:
        limitations.append(
            f"Запрошенный период ({routing.period_days} дней) превышает доступные demo-данные (92 дня)."
        )

    return AnalysisPlan(
        skill=routing.skill,
        question=question,
        product_codes=routing.product_codes,
        period=PeriodSpec(
            current_days=routing.period_days,
            comparison="year_over_year" if routing.period_days >= 180 else "previous_equal_period",
        ),
        hypotheses=_build_legacy_hypotheses(routing.skill),
        limitations=limitations,
    )


def plan(
    question: str,
    routing: RoutingResult | None = None,
    dataset_context: list[ResolvedDatasetInput] | None = None,
) -> AnalysisPlan:
    if routing is None:
        routing = route_sync(question)

    warnings = _validate_product_codes(
        routing.product_codes,
        allow_catalog_lookup=not dataset_context,
    )

    if not API_KEY:
        return _fallback_plan(question, routing, warnings, dataset_context=dataset_context)

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=MODEL_NAME, api_key=API_KEY, temperature=0)
        structured_llm = llm.with_structured_output(AnalysisPlan)
        result = structured_llm.invoke(_build_messages(question, routing, dataset_context))
        if warnings:
            result.limitations.extend(warnings)
        return result
    except Exception:
        return _fallback_plan(question, routing, warnings, dataset_context=dataset_context)


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python -m agent.planner "Question"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    result = plan(question)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
