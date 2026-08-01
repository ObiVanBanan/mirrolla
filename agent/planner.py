"""
Planner for Mirrolla analyses.
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

from agent.router import route_sync
from agent.schemas import AnalysisMode, AnalysisPlan, Hypothesis, PeriodSpec, RoutingResult, SkillType
from application.datasets.execution import (
    ResolvedDatasetInput,
    serialize_untrusted_dataset_context,
)

load_dotenv()

MODEL_NAME = os.getenv("PLANNER_MODEL", "gpt-4o")
API_KEY = os.getenv("token", "")
SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
PRODUCTS_PATH = os.path.join("data", "prepared", "products.json")

BASE_PROMPT = """Ты — планировщик аналитического анализа для Mirrolla.

Сформируй план только из вопроса пользователя, режима анализа и доступного контекста.

Правила:
- работай только с приложенными DatasetVersion, если они переданы;
- используй только реально существующие файлы, листы и колонки из профилей;
- не придумывай demo-файлы, несуществующие колонки и бизнес-контекст;
- определи минимальный набор действий, нужный для ответа;
- для простого запроса достаточно одной гипотезы;
- если данных не хватает, явно укажи это в limitations.
"""

LEGACY_DATASET_BLOCK = """## Available demo datasets
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
    revision_feedback: str | None = None,
) -> list[dict]:
    skill_md = _load_skill_md(routing.skill) if routing.skill is not None else ""
    skill_label = routing.skill.value if routing.skill is not None else "none"
    if dataset_context:
        system = (
            f"{BASE_PROMPT}\n\n"
            f"## Analysis mode\n{routing.analysis_mode.value}\n\n"
            + "## Attached planning mode\n"
            + "Build the plan only from attached dataset profiles and the user question.\n"
            + "Do not assume any hidden demo datasets, products catalog, or fixed time range.\n\n"
            + _build_dataset_context_block(dataset_context)
        )
    else:
        system = (
            f"{BASE_PROMPT}\n\n"
            f"## Analysis mode\n{routing.analysis_mode.value}\n\n"
            + (f"## Skill instructions\n{skill_md}\n\n" if skill_md else "")
            + (LEGACY_DATASET_BLOCK if routing.skill is not None else "")
        )

    user = "\n".join(
        [
            f"Вопрос менеджера: {question}",
            f"Analysis mode: {routing.analysis_mode.value}",
            f"Skill: {skill_label}",
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
    dataset_ids = [item.dataset_version_id for item in dataset_context]
    return AnalysisPlan(
        analysis_mode=routing.analysis_mode,
        skill=routing.skill,
        question=question,
        product_codes=routing.product_codes,
        period=PeriodSpec(current_days=routing.period_days, comparison="previous_equal_period"),
        hypotheses=[
            Hypothesis(
                id="H1",
                title="Выполнить запрошенную операцию над прикреплённым датасетом",
                datasets=dataset_ids,
                method=(
                    "Прочитать выбранные версии, проверить реальные колонки и выполнить "
                    "фильтрацию, агрегацию, подсчёт или проверку, указанную в вопросе."
                ),
                helpers=[],
            )
        ],
        limitations=[
            *extra_warnings,
            "План построен только по профилям прикреплённых файлов без использования demo-датасетов.",
        ],
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
    if routing.period_days > 92 and routing.skill is not None:
        limitations.append(
            f"Запрошенный период ({routing.period_days} дней) превышает доступные demo-данные (92 дня)."
        )

    hypotheses = (
        _build_legacy_hypotheses(routing.skill)
        if routing.skill is not None
        else [
            Hypothesis(
                id="H1",
                title="Ответить на вопрос по доступным данным",
                datasets=["available-data"],
                method="Выполнить минимально необходимую операцию для ответа на вопрос.",
                helpers=[],
            )
        ]
    )

    return AnalysisPlan(
        analysis_mode=routing.analysis_mode,
        skill=routing.skill,
        question=question,
        product_codes=routing.product_codes,
        period=PeriodSpec(
            current_days=routing.period_days,
            comparison="year_over_year" if routing.period_days >= 180 else "previous_equal_period",
        ),
        hypotheses=hypotheses,
        limitations=limitations,
    )


def plan(
    question: str,
    routing: RoutingResult | None = None,
    dataset_context: list[ResolvedDatasetInput] | None = None,
    revision_feedback: str | None = None,
) -> AnalysisPlan:
    if routing is None:
        routing = route_sync(question, dataset_context=dataset_context)

    warnings = _validate_product_codes(
        routing.product_codes,
        allow_catalog_lookup=not dataset_context,
    )

    planning_question = question
    if revision_feedback:
        planning_question = (
            f"{question}\n\n"
            f"Manager revision request: {revision_feedback}"
        )

    if not API_KEY:
        result = _fallback_plan(planning_question, routing, warnings, dataset_context=dataset_context)
        result.question = question
        if revision_feedback:
            if result.hypotheses:
                result.hypotheses[0].method = (
                    f"{result.hypotheses[0].method} "
                    f"Additional manager revision request: {revision_feedback}."
                )
            result.limitations.insert(0, f"Manager revision request: {revision_feedback}")
        return result

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=MODEL_NAME, api_key=API_KEY, temperature=0)
        structured_llm = llm.with_structured_output(AnalysisPlan)
        result = structured_llm.invoke(_build_messages(planning_question, routing, dataset_context))
        if warnings:
            result.limitations.extend(warnings)
        if revision_feedback:
            result.question = question
            if result.hypotheses:
                result.hypotheses[0].method = (
                    f"{result.hypotheses[0].method} "
                    f"Additional manager revision request: {revision_feedback}."
                )
            result.limitations.insert(0, f"Manager revision request: {revision_feedback}")
        if result.analysis_mode is None:
            result.analysis_mode = routing.analysis_mode
        if result.skill is None and routing.analysis_mode == AnalysisMode.SPECIALIZED:
            result.skill = routing.skill
        return result
    except Exception:
        result = _fallback_plan(planning_question, routing, warnings, dataset_context=dataset_context)
        result.question = question
        if revision_feedback:
            if result.hypotheses:
                result.hypotheses[0].method = (
                    f"{result.hypotheses[0].method} "
                    f"Additional manager revision request: {revision_feedback}."
                )
            result.limitations.insert(0, f"Manager revision request: {revision_feedback}")
        return result


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python -m agent.planner "Question"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    result = plan(question)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
