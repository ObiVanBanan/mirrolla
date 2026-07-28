"""
agent/planner.py — Planner: формирование плана анализа.

Читает SKILL.md выбранного skill'а и генерирует структурированный план:
  - гипотезы (3-5 штук)
  - датасеты для каждой гипотезы
  - метод проверки
  - ограничения

Запуск:
    python -m agent.planner "Почему упали продажи ЦБ-00007397?"
"""

import os
import sys
import json

from dotenv import load_dotenv
from pydantic import ValidationError

from application.datasets.execution import ResolvedDatasetInput

from agent.schemas import (
    SkillType,
    RoutingResult,
    AnalysisPlan,
    PeriodSpec,
    Hypothesis,
)
from agent.router import route_sync

load_dotenv()

MODEL_NAME = os.getenv("PLANNER_MODEL", "gpt-4o")
API_KEY = os.getenv("token", "")

# === Путь к skills ===
SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")

# === Каталог продуктов (для валидации product_code) ===
PRODUCTS_PATH = os.path.join("data", "prepared", "products.json")


# === System Prompt (база) ===

BASE_PROMPT = """Ты — планировщик аналитического анализа для Mirrolla.

Твоя задача: по вопросу менеджера, выбранному skill и периоду сформировать план анализа.

## Главное правило:
**Гипотезы ДОЛЖНЫ зависеть от периода анализа.** Не выдавай одинаковые гипотезы для 7 дней и 365 дней.

### Зависимость гипотез от периода:
- **1-7 дней (короткий):** операционные причины — out-of-stock, технический сбой, резкий негативный всплеск. Сезонность НЕ релевантна.
- **14-30 дней (средний):** сбалансированный анализ — остатки, отзывы, динамика категории, умеренная сезонность.
- **60-180 дней (длинный):** стратегические причины — долгосрочный тренд, сезонность, накопленные отзывы, хронический дефицит.
- **365+ дней (годовой):** годовая сезонность, структурные изменения рынка. Но если данных меньше периода → limitation!

### Проверка доступности данных:
Данные Ozon доступны за период: 17.03.2026 — 16.06.2026 (≈92 дня).
WB отзывы: 17.03.2026 — 17.06.2026.
1С остатки: только текущий snapshot (нет истории).
Если запрошенный период превышает доступные данные — ДОБАВЬ В LIMITATIONS предупреждение.

## Правила формирования плана:
1. Гипотезы (3-5 штук) — выбирай РЕЛЕВАНТНЫЕ периоду из SKILL.md (кандидаты с пометкой «Когда выбирать»)
2. Для каждой гипотезы — датасеты (строго из доступных) и метод (конкретный)
3. Для каждой гипотезы — helpers: список конкретных функций из helpers/, нужных для проверки
4. Ограничения — чего нет в данных, что нельзя проверить
5. comparison: "previous_equal_period" (текущий vs предыдущий равный период) для period < 90 дней; "year_over_year" для period ≥ 180 дней (если данных хватает)
6. ID гипотез: H1, H2, H3, ... (порядок = приоритет, без пропусков номеров)

## КРИТИЧЕСКОЕ ПРАВИЛО ПОЛНОТЫ:
- Верни ВСЕ проверяемые гипотезы из SKILL.md (3-5 штук).
- Исключай гипотезу ТОЛЬКО если данных физически нет (указано в SKILL.md как ограничение).
- Если вопрос звучит узко (например "что растёт быстрее рынка"), это НЕ повод отрезать гипотезы — план должен быть полным.
- Не сокращай план только потому что вопрос кажется простым.

## Принципы (Principled Instructions):
- Будь конкретным: метод = действие, не абстракция
- Будь честным: если данных нет → limitations, не выдумывай
- Адаптируйся: разные периоды = разные гипотезы
- Не дублируй: helpers — только релевантные функции, не весь файл
"""


def _load_skill_md(skill: SkillType) -> str:
    """Загрузить SKILL.md для выбранного skill'а."""
    skill_dir = os.path.join(SKILLS_DIR, skill.value)
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        raise FileNotFoundError(f"SKILL.md не найден: {skill_path}")
    with open(skill_path, "r", encoding="utf-8") as f:
        return f.read()


def _validate_product_codes(codes: list[str]) -> list[str]:
    """
    Проверить, что product_codes существуют в каталоге 1С.

    Returns:
        list[str]: предупреждения для несуществующих кодов
    """
    if not codes:
        return []

    warnings = []
    try:
        with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
            products = json.load(f)
        existing_codes = {p["code"] for p in products if isinstance(p, dict) and "code" in p}
        for code in codes:
            if code not in existing_codes:
                warnings.append(f"Код товара {code} не найден в каталоге 1С (products.json)")
    except FileNotFoundError:
        warnings.append(f"Каталог products.json недоступен — валидация кодов пропущена")
    except Exception as e:
        warnings.append(f"Ошибка валидации кодов: {e}")

    return warnings
def _build_dataset_context_block(dataset_context: list[ResolvedDatasetInput] | None) -> str:
    if not dataset_context:
        return ""

    lines = [
        "## Attached dataset profiles",
        "These are the factual datasets for the current analysis.",
        "Do not assume files, sheets, or columns that are not present below.",
        "Do not use raw dataset rows beyond these profile summaries.",
    ]
    for item in dataset_context:
        lines.append(
            f"### dataset_version_id={item.dataset_version_id} | display_name={item.display_name} | format={item.format}"
        )
        for sheet in item.profile.sheets:
            lines.append(
                f"- sheet: {sheet.name} | row_count={sheet.row_count} | sampled={sheet.sampled}"
            )
            for warning in sheet.warnings:
                lines.append(f"  - warning: {warning}")
            for column in sheet.columns:
                parts = [
                    f"  - column: {column.name}",
                    f"type={column.inferred_type}",
                    f"null_ratio={column.null_ratio:.3f}",
                ]
                if column.unique_count is not None:
                    parts.append(f"unique={column.unique_count}")
                if column.min_value is not None:
                    parts.append(f"min={column.min_value}")
                if column.max_value is not None:
                    parts.append(f"max={column.max_value}")
                if column.examples:
                    parts.append(f"examples={', '.join(column.examples)}")
                lines.append(" | ".join(parts))
        for warning in item.profile.warnings:
            lines.append(f"- profile_warning: {warning}")

    return "\n".join(lines)


def _build_messages(
    question: str,
    routing: RoutingResult,
    dataset_context: list[ResolvedDatasetInput] | None = None,
) -> list[dict]:
    """Собрать messages для LLM: system + user."""
    skill_md = _load_skill_md(routing.skill)

    system = f"""{BASE_PROMPT}

## Выбранный skill: {routing.skill.value}

## Инструкция skill'а (SKILL.md):

{skill_md}

## Доступные датасеты (жёсткий список — не выдумывай):
- sales — Ozon orders по дням
- stocks — 1С остатки (текущий snapshot)
- reviews_wb — WB отзывы
- reviews_ozon — Ozon отзывы (внутри sales)
- categories — 1С productType (категория товара)
"""
    dataset_block = _build_dataset_context_block(dataset_context)
    if dataset_block:
        system = f"{system}\n\n{dataset_block}"

    user_parts = [
        f"Вопрос менеджера: {question}",
        f"Skill: {routing.skill.value}",
    ]
    if routing.product_codes:
        user_parts.append(f"Коды товаров: {', '.join(routing.product_codes)}")
    else:
        user_parts.append("Коды товаров: не указаны (анализ по всему портфелю)")
    user_parts.append(f"Период анализа: {routing.period_days} дней")

    user = "\n".join(user_parts)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def plan(
    question: str,
    routing: RoutingResult | None = None,
    dataset_context: list[ResolvedDatasetInput] | None = None,
) -> AnalysisPlan:
    """
    Сформировать план анализа.

    Args:
        question: вопрос менеджера.
        routing: результат Router (если None — вызовет Router автоматически).

    Returns:
        AnalysisPlan: структурированный план с гипотезами.
    """
    # Шаг 1: Route (если routing не передан)
    if routing is None:
        print(f"  [Planner] Router не передан, вызываю Router...")
        routing = route_sync(question)
        print(f"  [Planner] Router → skill={routing.skill.value}, codes={routing.product_codes}, period={routing.period_days}")

    # Шаг 2: Валидация product_codes
    warnings: list[str] = []
    if routing.product_codes:
        warnings = _validate_product_codes(routing.product_codes)
        for w in warnings:
            print(f"  [Planner] ⚠ {w}")

    # Шаг 3: LLM генерация плана
    if not API_KEY:
        print("  [Planner] ⚠ API ключ не найден, использую fallback-план")
        return _fallback_plan(question, routing, warnings)

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=MODEL_NAME,
            api_key=API_KEY,
            temperature=0,
        )
        structured_llm = llm.with_structured_output(AnalysisPlan)
        messages = _build_messages(question, routing, dataset_context)
        result = structured_llm.invoke(messages)

        # Добавляем warnings в limitations
        if warnings:
            result.limitations.extend(warnings)

        return result

    except Exception as e:
        print(f"  [Planner] ⚠ LLM ошибся: {e}")
        print("  [Planner] → fallback на статический план")
        return _fallback_plan(question, routing, warnings)


def _fallback_plan(question: str, routing: RoutingResult, extra_warnings: list[str]) -> AnalysisPlan:
    """
    Статический план без LLM — по шаблонам из SKILL.md.
    Каждый skill имеет предопределённые гипотезы.
    """
    skill = routing.skill
    period = PeriodSpec(current_days=routing.period_days, comparison="previous_equal_period")

    plans: dict[SkillType, list[Hypothesis]] = {
        SkillType.SALES_DECLINE: [
            Hypothesis(id="H1", title="Дефицит остатков", datasets=["sales", "stocks"],
                       method="Сопоставить ежедневные продажи с остатками. Если продажи упали при критических остатках — причина в out-of-stock.",
                       helpers=["compare_periods", "stockout_days", "critical_stocks", "out_of_stock"]),
            Hypothesis(id="H2", title="Изменение цены", datasets=["sales"],
                       method="Сравнить среднюю цену двух периодов. ⚠️ Нет колонки цены — гипотеза не проверяема.",
                       helpers=["compare_periods"]),
            Hypothesis(id="H3", title="Рост негативных отзывов", datasets=["reviews_wb", "reviews_ozon"],
                       method="Сравнить средний рейтинг и долю негативных отзывов (1-2★) текущего и предыдущего периода.",
                       helpers=["negative_reviews_wb", "negative_reviews_ozon", "review_summary"]),
            Hypothesis(id="H4", title="Динамика категории", datasets=["sales", "categories"],
                       method="Сравнить продажи товара с продажами его категории (productType). Если категория тоже упала — проблема рыночная.",
                       helpers=["category_growth_by_type", "faster_than_market", "load_product_categories"]),
            Hypothesis(id="H5", title="Сезонность / общий тренд", datasets=["sales"],
                       method="Посмотреть тренд заказов по дням за весь период. Падение может быть сезонным.",
                       helpers=["daily_order_counts", "compare_periods", "category_growth"]),
        ],
        SkillType.INVENTORY: [
            Hypothesis(id="H1", title="Критические остатки (< 7 дней)", datasets=["sales", "stocks"],
                       method="Рассчитать средние дневные продажи → разделить остаток на скорость → дни запаса. Фильтр < 7 дней.",
                       helpers=["daily_order_counts", "stockout_days", "critical_stocks"]),
            Hypothesis(id="H2", title="Полный out-of-stock", datasets=["stocks"],
                       method="Найти товары с balance=0, у которых есть продажи (спрос есть, товара нет).",
                       helpers=["out_of_stock", "stockout_days"]),
            Hypothesis(id="H3", title="Рекомендация по производству", datasets=["sales", "stocks"],
                       method="Рекомендуемое производство = спрос за цикл (14д) + страховой запас (7д) − текущий остаток.",
                       helpers=["daily_order_counts", "stockout_days", "production_plan"]),
            Hypothesis(id="H4", title="Тренд спроса", datasets=["sales"],
                       method="Оценить растёт или падает спрос — влияет на рекомендуемый объём производства.",
                       helpers=["daily_order_counts", "compare_periods"]),
        ],
        SkillType.PORTFOLIO_GROWTH: [
            Hypothesis(id="H1", title="Топ-10 растущих товаров", datasets=["sales"],
                       method="Сравнить заказы текущего и предыдущего периода, отсортировать по % роста. Фильтр min_orders.",
                       helpers=["load_ozon", "compare_periods", "top_growth"]),
            Hypothesis(id="H2", title="Топ-10 падающих товаров", datasets=["sales"],
                       method="То же, но по убыванию роста.",
                       helpers=["load_ozon", "compare_periods", "top_decline"]),
            Hypothesis(id="H3", title="Рост по категориям (productType)", datasets=["sales", "categories"],
                       method="Группировать продажи по productType, сравнить периоды.",
                       helpers=["load_ozon", "compare_periods", "category_growth_by_type", "load_product_categories"]),
            Hypothesis(id="H4", title="Товары быстрее своей категории", datasets=["sales", "categories"],
                       method="Для каждого товара сравнить его рост с ростом его категории. Delta = товар − категория.",
                       helpers=["load_ozon", "compare_periods", "faster_than_market", "load_product_categories"]),
        ],
        SkillType.REVIEWS_PRICING: [
            Hypothesis(id="H1", title="Негативные отзывы WB (1-2★)", datasets=["reviews_wb"],
                       method="Фильтр rating <= 2, сортировка по дате. Показать последние негативные отзывы.",
                       helpers=["load_wb_reviews", "negative_reviews_wb"]),
            Hypothesis(id="H2", title="Негативные отзывы Ozon (1-2★)", datasets=["reviews_ozon"],
                       method="Фильтр rating <= 2, выборка с текстом отзыва.",
                       helpers=["load_ozon", "negative_reviews_ozon"]),
            Hypothesis(id="H3", title="Повторяющиеся жалобы", datasets=["reviews_wb"],
                       method="Группировать негативные отзывы по product_code, найти товары с множественными жалобами.",
                       helpers=["load_wb_reviews", "recurring_complaints"]),
            Hypothesis(id="H4", title="Товары, требующие ответа", datasets=["reviews_wb"],
                       method="Найти отзывы без ответа продавца (колонка 'Ответ' = NaN).",
                       helpers=["load_wb_reviews", "reviews_requiring_response"]),
            Hypothesis(id="H5", title="Кандидаты на изменение цены", datasets=["reviews_wb", "reviews_ozon", "sales"],
                       method="Товары с высоким негативом + стабильным спросом → снижение цены. Высокие оценки + рост → повышение. ⚠️ Нет цен — только качественная рекомендация.",
                       helpers=["review_summary", "compare_periods", "negative_reviews_wb"]),
        ],
    }

    # Проверка: период превышает доступные данные?
    DATA_RANGE_DAYS = 92  # Ozon: 17.03-16.06.2026
    if routing.period_days > DATA_RANGE_DAYS:
        extra_warnings.append(
            f"Запрошенный период ({routing.period_days} дней) превышает доступные данные ({DATA_RANGE_DAYS} дней). "
            f"Анализ будет ограничен доступным диапазоном."
        )

    # Выбор гипотез по периоду
    period_days = routing.period_days

    if period_days <= 7:
        # Короткий — операционные причины
        hypotheses = [
            Hypothesis(id="H1", title="Out-of-stock / технический сбой", datasets=["sales", "stocks"],
                       method="Проверить резко ли упали продажи (к ~0), сравнить с остатками. Если остаток=0 при спросе — причина.",
                       helpers=["compare_periods", "stockout_days", "out_of_stock"]),
            Hypothesis(id="H2", title="Резкий негативный всплеск", datasets=["reviews_wb"],
                       method="Проверить всплеск негативных отзывов (1-2★) в последние дни.",
                       helpers=["negative_reviews_wb", "reviews_requiring_response"]),
        ]
        comparison = "previous_equal_period"
    elif period_days <= 30:
        # Средний — сбалансированный
        hypotheses = [
            Hypothesis(id="H1", title="Дефицит остатков", datasets=["sales", "stocks"],
                       method="Сопоставить продажи с остатками. Out-of-stock если продажи упали при критических остатках.",
                       helpers=["compare_periods", "stockout_days", "critical_stocks", "out_of_stock"]),
            Hypothesis(id="H2", title="Рост негативных отзывов", datasets=["reviews_wb", "reviews_ozon"],
                       method="Сравнить средний рейтинг и долю негативных отзывов (1-2★) текущего и предыдущего периода.",
                       helpers=["negative_reviews_wb", "negative_reviews_ozon", "review_summary"]),
            Hypothesis(id="H3", title="Динамика категории", datasets=["sales", "categories"],
                       method="Сравнить продажи товара с его категорией (productType). Если категория тоже упала — проблема рыночная.",
                       helpers=["category_growth_by_type", "faster_than_market", "load_product_categories"]),
            Hypothesis(id="H4", title="Сезонность / тренд", datasets=["sales"],
                       method="Тренд заказов по дням. Падение может быть сезонным.",
                       helpers=["daily_order_counts", "compare_periods", "category_growth"]),
        ]
        comparison = "previous_equal_period"
    else:
        # Длинный (60+) — стратегические причины
        hypotheses = [
            Hypothesis(id="H1", title="Долгосрочный тренд / сезонность", datasets=["sales"],
                       method="Анализ тренда за весь период, выявление сезонных паттернов и общего направления.",
                       helpers=["daily_order_counts", "compare_periods", "category_growth"]),
            Hypothesis(id="H2", title="Накопленные негативные отзывы", datasets=["reviews_wb", "reviews_ozon"],
                       method="Оценить накопленный негатив за весь период, не просто сравнение периодов. Рекуррентные жалобы.",
                       helpers=["review_summary", "recurring_complaints", "negative_reviews_wb"]),
            Hypothesis(id="H3", title="Хронический дефицит остатков", datasets=["sales", "stocks"],
                       method="Проверить системные проблемы с поставками. Производственный план.",
                       helpers=["stockout_days", "critical_stocks", "production_plan"]),
            Hypothesis(id="H4", title="Динамика категории", datasets=["sales", "categories"],
                       method="Сравнить продажи товара с его категорией за весь период. Рыночный тренд.",
                       helpers=["category_growth_by_type", "faster_than_market", "load_product_categories"]),
        ]
        comparison = "year_over_year" if period_days >= 180 else "previous_equal_period"

    # Для остальных skill'ов (inventory, portfolio, reviews) используем шаблоны
    limitations_map: dict[SkillType, list[str]] = {
        SkillType.INVENTORY: [
            "Нет поставок в пути (считаем = 0)",
            "Остатки — только текущий snapshot (нет истории)",
            "Нет себестоимости",
            "WB заказы не доступны — спрос только по Ozon",
        ],
        SkillType.PORTFOLIO_GROWTH: [
            "Рынок = категория внутри данных Mirrolla",
            "Нет цен → рост в заказах, не в выручке",
            "WB заказы не доступны — только Ozon",
        ],
        SkillType.REVIEWS_PRICING: [
            "Нет цены продажи — нельзя рассчитать оптимальную цену",
            "Нет цен конкурентов",
            "Продавец не отвечает на отзывы WB (все NaN)",
            "~80% отзывов Ozon без текста",
        ],
    }

    limitations: list[str] = []
    if skill != SkillType.SALES_DECLINE:
        hypotheses = plans[skill]
        limitations = limitations_map.get(skill, [])
        comparison = "previous_equal_period"
    limitations.extend(extra_warnings)

    # Применить вычисленный comparison к period (иначе всегда previous_equal_period)
    period = period.model_copy(update={"comparison": comparison})

    return AnalysisPlan(
        skill=skill,
        question=question,
        product_codes=routing.product_codes,
        period=period,
        hypotheses=hypotheses,
        limitations=limitations,
    )


# === CLI ===

def main():
    if len(sys.argv) < 2:
        print("Использование: python -m agent.planner \"Вопрос менеджера\"")
        print()
        print("Примеры:")
        print('  python -m agent.planner "Почему упали продажи ЦБ-00007397?"')
        print('  python -m agent.planner "Что заканчивается на складе?"')
        print('  python -m agent.planner "Какие отзывы плохие?"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"Вопрос: {question}")
    print()

    result = plan(question)

    print("План анализа:")
    print(json.dumps(
        result.model_dump(),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
