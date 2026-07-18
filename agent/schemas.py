"""
agent/schemas.py — Pydantic-модели для агента.

Определяют контракт между Router → Planner → Executor.
"""

from enum import Enum
from pydantic import BaseModel, Field


class SkillType(str, Enum):
    """4 аналитических skill-класса."""

    SALES_DECLINE = "sales-decline-analysis"
    INVENTORY = "inventory-planning"
    PORTFOLIO_GROWTH = "portfolio-growth"
    REVIEWS_PRICING = "reviews-and-pricing"


class Question(BaseModel):
    """Вход: вопрос менеджера."""

    text: str = Field(..., description="Вопрос менеджера на русском языке")


class RoutingResult(BaseModel):
    """Выход Router: какой skill нужен + параметры."""

    skill: SkillType = Field(
        ...,
        description="Аналитический skill для ответа на вопрос",
    )
    product_codes: list[str] = Field(
        default_factory=list,
        description="Коды товаров из вопроса (ЦБ-XXXXXXXX или ФР-XXXXXXXX). Пустой список, если вопрос не про конкретный товар.",
    )
    period_days: int = Field(
        default=14,
        ge=1,
        le=365,
        description="Период анализа в днях. По умолчанию 14.",
    )


class PeriodSpec(BaseModel):
    """Спецификация периода анализа."""

    current_days: int = Field(
        ...,
        ge=1,
        le=365,
        description="Длина текущего периода в днях",
    )
    comparison: str = Field(
        default="previous_equal_period",
        description="Метод сравнения: previous_equal_period, year_over_year, ...",
    )


class Hypothesis(BaseModel):
    """Одна гипотеза анализа."""

    id: str = Field(..., description="Идентификатор: H1, H2, H3, ...")
    title: str = Field(..., description="Краткое название гипотезы")
    datasets: list[str] = Field(
        ..., description="Датасеты для проверки: sales, stocks, reviews_wb, reviews_ozon, categories"
    )
    method: str = Field(..., description="Метод проверки гипотезы (что именно сделать)")
    helpers: list[str] = Field(
        default_factory=list,
        description="Имена конкретных функций из helpers/ для этой гипотезы. Executor будет читать исходник только этих функций и передавать в LLM prompt. Пример: ['compare_periods', 'stockout_days']",
    )


class AnalysisPlan(BaseModel):
    """Полный план анализа — выход Planner."""

    skill: SkillType = Field(..., description="Аналитический skill")
    question: str = Field(..., description="Исходный вопрос менеджера")
    product_codes: list[str] = Field(
        default_factory=list,
        description="Коды товаров для анализа",
    )
    period: PeriodSpec = Field(..., description="Период анализа")
    hypotheses: list[Hypothesis] = Field(
        ...,
        description="Гипотезы для проверки (3-5 штук)",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Ограничения: чего нет в данных, что нельзя проверить",
    )


class HypothesisResult(BaseModel):
    """Результат проверки одной гипотезы."""

    hypothesis_id: str = Field(..., description="ID гипотезы: H1, H2, ...")
    title: str = Field(..., description="Название гипотезы")
    confirmed: bool | None = Field(
        None,
        description="True — подтверждена, False — опровергнута, None — недостаточно данных",
    )
    detail: str = Field(..., description="Что выяснилось по гипотезе")
    data: dict | None = Field(
        None,
        description="Численные результаты (метрики, цифры)",
    )


class Finding(BaseModel):
    """Конкретный объект в результате анализа — товар, отзыв или категория.

    Универсальная единица ответа: вместо счётчика «3520 товаров»
    CI возвращает список конкретных объектов с причинами и действием.
    """

    entity_type: str = Field(
        ...,
        description="Тип объекта: product, review, category",
    )
    entity_id: str = Field(
        ...,
        description="Идентификатор: product_code (ЦБ-XXXXXXXX) или review_id",
    )
    name: str = Field(..., description="Название товара/категории")
    priority: str = Field(
        "medium",
        description="Приоритет: critical, high, medium, low",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Конкретные причины с цифрами, почему объект в результате",
    )
    metrics: dict = Field(
        default_factory=dict,
        description="Рассчитанные показатели: {sales_current: 120, change_pct: -36.8}",
    )
    recommended_action: str = Field(
        "",
        description="Конкретное действие менеджера",
    )


class ExecutionResult(BaseModel):
    """Результат выполнения анализа — выход Executor."""

    question: str = Field(..., description="Исходный вопрос менеджера")
    skill: SkillType = Field(..., description="Использованный skill")
    answer_status: str = Field(
        "answered",
        description="Статус ответа: answered, partial, not_enough_data",
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="Конкретные объекты (товары/отзывы) с причинами и действиями",
    )
    hypothesis_results: list[HypothesisResult] = Field(
        default_factory=list,
        description="Результаты по гипотезам (опционально, не основной формат)",
    )
    charts: list[str] = Field(
        default_factory=list,
        description="Пути к PNG файлам графиков",
    )
    summary: str = Field(
        "",
        description="Человекочитаемый ответ менеджеру (от Reporter LLM)",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Ограничения анализа",
    )
    code_generated: str | None = Field(
        None,
        description="Python код, сгенерированный LLM",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Ошибки при выполнении",
    )