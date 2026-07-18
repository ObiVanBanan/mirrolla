# Mirrolla AI Data Analyst — Архитектурное решение

> **Дата:** 2026-07-16
> **Статус:** Day 1 завершён, Days 2-3 в работе
> **Оптимизация:** time-to-ship (пилот, 5 рабочих дней) → простота оперирования → честность об ограничениях

---

## 1. Контекст и цели

### Бизнес-задача

Менеджер Mirrolla (WB + Ozon) тратит несколько часов в день на ручной анализ продаж, остатков, отзывов. Нужен AI-ассистент, который отвечает на 6 типов вопросов и формирует авто-отчёт.

### Жёсткие ограничения (подтверждены разведкой)

| # | Ограничение | Источник |
|---|-------------|----------|
| C1 | **Нет цен продажи** — ни в Ozon, ни в WB, ни в 1С (`ProductSales` отдаёт только `quantity`) | `data_research.md`, `decisions.md` R1 |
| C2 | **Нет продаж WB** — WB-выгрузка содержит только отзывы (4 132 строк) | `decisions.md` R3 |
| C3 | **Фильтр по кодам в 1С API не работает** — всегда отдаёт весь список | `api_research.md`, `decisions.md` R4 |
| C4 | **articleOzon / articleWb заполнены у 11-13% товаров** — маппинг только по `code` (ЦБ-XXXXXXXX / ФР-XXXXXXXX) | `api_research.md` |
| C5 | **1С доступна только через VPN** (HTTP, не HTTPS, Basic Auth) — с машины разработчика | `api_research.md` |
| C6 | **ProductSales агрегирует за период**, не по дням — для дневных данных вызывать по 1 дню | `api_research.md` |
| C7 | **Остатки — текущий snapshot**, без истории | `api_research.md` |

### Non-goals (явно исключаем)

- Полноценный SEO-анализ (нет поисковых позиций, CTR, данных конкурентов)
- Точные рекомендации по цене (нет цен, себестоимости, комиссий)
- Сравнение продаж WB vs Ozon (нет продаж WB — C2)
- Реальная 1С (тестовый API через VPN)

### Качественные атрибуты (по приоритету)

1. **Time-to-ship** — 2 дня до дедлайна; каждый компонент должен запускаться независимо
2. **Честность** — UI/README явно показывают ограничения данных
3. **Простота оперирования** — одна команда `docker compose up`, минимум сервисов
4. **Воспроизводимость** — детерминированные расчёты (helpers) + LLM только для рассуждений

---

## 2. Текущее состояние (Day 1 — завершён)

### Что работает

```
✅ client/onec_client.py     — OneCClient: get_products / get_balances / get_sales
✅ helpers/sales.py           — load_ozon, compare_periods, top_growth, top_decline,
                                category_growth_by_type, faster_than_market, analyze_decline
✅ helpers/stocks.py          — stockout_days, critical_stocks, out_of_stock, production_plan
✅ helpers/reviews.py        — negative_reviews_wb/ozon, review_summary,
                                reviews_requiring_response, recurring_complaints
✅ run_analytics.py          — контрольный прогон всех 6 разделов без LLM
✅ data/prepared/products.json — 3 854 товара из 1С (5.7 MB)
```

### Покрытие вопросов ТЗ (без LLM)

| # | Вопрос | Статус | Реализация |
|---|--------|--------|------------|
| 1 | Почему снизились продажи? | ✅ | `analyze_decline()` — 5 гипотез (H1-H5) |
| 2 | Какие товары заканчиваются? | ✅ | `critical_stocks()` + `out_of_stock()` |
| 3 | Что заказать в производство? | ✅ | `production_plan()` |
| 4 | Растут быстрее рынка? | ✅ | `faster_than_market()` по productType |
| 5 | Какие отзывы требуют реакции? | ✅ | `reviews_requiring_response()` + `recurring_complaints()` |
| 6 | Требуют изменения цены? | ❌ | Нет данных (C1) |

**Ключевой вывод:** аналитическое ядро готово. Оставшиеся 2 дня — это LLM-слой, HITL, API, UI, Docker.

---

## 3. Предлагаемая архитектура

### 3.1 Execution: Code Interpreter + Skills-as-Prompt

```
┌─────────────────────────────────────────────────────┐
│         LangGraph (оркестрация + HITL)               │
│  understand → select_skill → plan → interrupt        │
│  StateGraph + SqliteSaver checkpointer               │
│  Модель: gpt-4o (reasoning: классификация, план)     │
└────────────────────────┬────────────────────────────┘
                         │ approved plan + skill + reference code
                         ▼
┌─────────────────────────────────────────────────────┐
│         Code Interpreter (sandbox выполнения)         │
│  OpenAI Assistant + uploaded Parquet files           │
│  System prompt = SKILL.md + helpers reference +      │
│                  dataset schema + approved plan       │
│  Модель пишет Python, запускает, исправляет ошибки,  │
│  строит графики (matplotlib → PNG)                   │
└────────────────────────┬────────────────────────────┘
                         │ results (JSON) + charts (PNG)
                         ▼
┌─────────────────────────────────────────────────────┐
│              LangGraph: synthesize                    │
│  gpt-4o формулирует ответ менеджеру на языке людей    │
│  + вставляет таблицы, графики, рекомендации           │
└─────────────────────────────────────────────────────┘
```

**Принцип:** LangGraph решает **что делать** (план, HITL). Code Interpreter решает **как считать** (код, графики). `helpers/` — это reference-материал для промпта, а не runtime-код. SKILL.md — инструкция «что анализировать».

### 3.2 LangGraph топология

```
                    ┌──────────────────┐
                    │  understand_node  │  gpt-4o: классифицирует вопрос,
                    │                   │         извлекает product_code, период
                    └────────┬──────────┘
                             ▼
                    ┌──────────────────┐
                    │  select_skill     │  gpt-4o: выбирает 1 из 4 skills
                    │                   │         по типу вопроса
                    └────────┬──────────┘
                             ▼
                    ┌──────────────────┐
                    │  generate_plan    │  gpt-4o: формирует AnalysisPlan
                    │                   │         (гипотезы, датасеты, метод)
                    └────────┬──────────┘
                             ▼
                    ┌──────────────────┐
                    │  interrupt()      │  ⏸ HITL checkpoint
                    │  Human Review     │  approve / revise / reject
                    └────────┬──────────┘
                             ▼ (approve)
                    ┌──────────────────┐
                    │  execute_ci      │  OpenAI Code Interpreter:
                    │                   │  собирает system prompt из
                    │                   │  SKILL.md + reference code +
                    │                   │  schema + approved plan,
                    │                   │  запускает run, получает
                    │                   │  results + charts
                    └────────┬──────────┘
                             ▼
                    ┌──────────────────┐
                    │  synthesize       │  gpt-4o: формулирует ответ
                    │                   │         менеджеру (русский, чёткий)
                    │                   │         + вставляет графики/таблицы
                    └──────────────────┘
```

**Checkpointer:** `SqliteSaver` — состояние HITL сохраняется между запросами. Для MVP этого достаточно (1 менеджер, локально).

### 3.3 Component map

```
mirrolla-ai/
├── client/onec_client.py      ✅ готово — OneCClient
├── helpers/                   ✅ готово — reference-код для CI system prompt
│   ├── sales.py               # compare_periods, analyze_decline, top_growth...
│   ├── stocks.py              # stockout_days, critical_stocks, production_plan
│   └── reviews.py             # negative_reviews, reviews_requiring_response...
├── agent/                    🔲 Day 2 — LangGraph + Code Interpreter
│   ├── graph.py              # StateGraph, checkpointer, interrupts
│   ├── nodes.py             # understand, select_skill, plan, execute_ci, synthesize
│   ├── ci_runner.py         # OpenAI Code Interpreter integration
│   │                         # - file upload (Parquet, one-time)
│   │                         # - system prompt assembly (skill + reference + schema)
│   │                         # - run + poll + extract results/charts
│   └── schemas.py           # Pydantic: AnalysisPlan, Question, Answer
├── skills/                   🔲 Day 2 — 4 SKILL.md (instruction text for CI prompt)
│   ├── sales-decline-analysis/SKILL.md
│   ├── inventory-planning/SKILL.md
│   ├── portfolio-growth/SKILL.md
│   └── reviews-and-pricing/SKILL.md
├── data/
│   ├── *.xlsx                ✅ исходные выгрузки
│   └── prepared/
│       ├── products.json     ✅ каталог из 1С
│       ├── ozon.parquet      🔲 Day 2 — нормализованный Ozon для CI
│       ├── wb_reviews.parquet 🔲 Day 2 — нормализованные WB отзывы для CI
│       └── balances.parquet  🔲 Day 2 — balances из 1С для CI
├── api/main.py               🔲 Day 3 — FastAPI
├── ui/streamlit_app.py       🔲 Day 3 — Streamlit chat
├── reports/generator.py      🔲 Day 3 — авто-отчёт (Jinja2 → HTML)
├── compose.yaml              🔲 Day 3 — Docker Compose
├── Dockerfile                🔲 Day 3
├── .env.example              🔲 Day 3
├── requirements.txt          🔲 Day 2
└── README.md                 🔲 Day 3
```

### 3.4 Data flow

```
Вопрос менеджера (через Streamlit)
    │
    ▼
FastAPI POST /api/v1/analyses
    │
    ▼
LangGraph: understand → select_skill → generate_plan
    │  (gpt-4o: классификация вопроса, выбор skill, план)
    ▼
interrupt() → Streamlit показывает план → approve
    │
    ▼ (approve)
agent/ci_runner.py:
    │
    │  1. Собирает system prompt:
    │     ├── SKILL.md (из skills/<selected>/SKILL.md)
    │     ├── Reference-код (из helpers/*.py — как текст)
    │     ├── Dataset schema (колонки, типы, file_ids)
    │     └── Approved plan (из HITL)
    │
    │  2. Создаёт/переиспользует OpenAI Assistant
    │     с tool_type="code_interpreter"
    │
    │  3. Загруженные Parquet file_ids передаются
    │     в message attachments
    │
    │  4. Runs the assistant, polls for completion
    │     LLM пишет Python в sandbox:
    │       df = pd.read_parquet(file_id)
    │       # воспроизводит логику из reference code
    │       # сравнивает периоды, считает days_of_stock,
    │       # анализирует отзывы, строит графики
    │     Если код упал → LLM сам исправляет → retry
    │
    ▼
LangGraph: synthesize
    │  (gpt-4o: формулирует ответ менеджеру
    │   на основе results + charts из CI)
    ▼
Streamlit: чат + таблицы + графики + рекомендации
```

---

## 4. Ключевое архитектурное решение: Code Interpreter (Sandbox) + Skills-as-Prompt

### Решение

**Использовать OpenAI Code Interpreter** для выполнения анализа.

**Не function calling.** Не локальные импорты. Модель сама пишет Python-код в sandbox, воспроизводя логику по reference-коду и SKILL.md из промпта.

### Как это работает — трёхкомпонентный промпт

Code Interpreter получает в system prompt три блока:

```
┌──────────────────────────────────────────────────────┐
│  System Prompt для Code Interpreter                  │
│                                                      │
│  ┌───────────────────────────────────────────────┐   │
│  │  1. SKILL.md (выбранный skill)                 │   │
│  │     → что анализировать, какие гипотезы,       │   │
│  │       какие шаги, какой формат ответа          │   │
│  │     → LangGraph выбрал skill по типу вопроса   │   │
│  └───────────────────────────────────────────────┘   │
│                                                      │
│  ┌───────────────────────────────────────────────┐   │
│  │  2. Reference-код из helpers/                  │   │
│  │     → логика расчётов (compare_periods,       │   │
│  │       stockout_days, production_plan, ...)     │   │
│  │     → образцы, а не runtime-импорт             │   │
│  │     → «пиши по этим образцам»                  │   │
│  └───────────────────────────────────────────────┘   │
│                                                      │
│  ┌───────────────────────────────────────────────┐   │
│  │  3. Dataset schema reference                  │   │
│  │     → какие файлы загружены (file_ids)         │   │
│  │     → колонки, типы, ключи, диапазон дат      │   │
│  │     → «читай через pd.read_parquet(file_id)»   │   │
│  └───────────────────────────────────────────────┘   │
│                                                      │
│  + Утверждённый план из HITL                          │
│                                                      │
│  → LLM пишет Python, запускает в sandbox,            │
│    сам исправляет ошибки, строит графики             │
└──────────────────────────────────────────────────────┘
```

### Архитектура выполнения

```
LangGraph:
  understand → select_skill → plan → interrupt(HITL)
                                              │
                                              ▼ (approve)
                                    ┌─────────────────────┐
                                    │  Code Interpreter   │
                                    │  (OpenAI sandbox)   │
                                    │                     │
                                    │  Вход:               │
                                    │  ├── Parquet files   │ ← uploaded once at startup
                                    │  │   (ozon, wb,      │
                                    │  │    balances)      │
                                    │  ├── SKILL.md        │ ← injected by select_skill node
                                    │  ├── Reference code  │ ← from helpers/*.py
                                    │  ├── Dataset schema  │ ← column docs
                                    │  └── Approved plan   │ ← from HITL
                                    │                     │
                                    │  Выход:              │
                                    │  ├── Results (JSON)  │
                                    │  ├── Tables (DataFrame→dict)
                                    │  ├── Charts (PNG)    │
                                    │  └── Recommendations │
                                    └────────┬────────────┘
                                             ▼
                                    synthesize → ответ менеджеру
```

### Почему Skills-as-Prompt, а не Skills-as-Code

| Подход | Что отправляется | Плюс | Минус |
|--------|------------------|------|------|
| **Skills-as-Code** (function calling) | @tool функции | Детерминированно, дёшево | 🔲 Только предопределённые сценарии |
| **Skills-as-Prompt** (выбран) | SKILL.md текст + reference code | ✅ Гибкость + self-correction + графики | ⚠️ Латентность, cost |
| **Гибрид** | Skill выбирает tool-set | Лучшее из обоих | 🔲 Сложнее, больше кода |

Для пилота на демо: Skills-as-Prompt даёт «вау-эффект» (AI пишет и запускает код), self-correction (страховка от багов), графики «из коробки».

### Загрузка данных

```python
# Один раз при старте приложения — file_id переиспользуется
files = {
    "ozon": client.files.create(
        file=open("data/prepared/ozon.parquet", "rb"),
        purpose="assistants"
    ).id,
    "wb_reviews": client.files.create(
        file=open("data/prepared/wb_reviews.parquet", "rb"),
        purpose="assistants"
    ).id,
    "balances": client.files.create(
        file=open("data/prepared/balances.parquet", "rb"),
        purpose="assistants"
    ).id,
    "products": client.files.create(
        file=open("data/prepared/products.parquet", "rb"),
        purpose="assistants"
    ).id,
}
```

Parquet — оптимальный формат: компактный (Ozon 170K строк → ~3 MB vs 20+ MB CSV), типизированный, pandas читает одной командой.

### Обоснование выбора

| Критерий | Code Interpreter (выбран) | Function Calling (отклонён) |
|----------|---------------------------|------------------------------|
| Гибкость | ✅ Любой анализ, ad-hoc вопросы | 🔲 Только 8 предопределённых функций |
| Self-correction | ✅ Упал → сам исправил → перезапустил | ❌ Упал → ошибка пользователю |
| Графики | ✅ matplotlib прямо в sandbox → PNG в чат | 🔲 Генерировать отдельно |
| Соответствие roadmap | ✅ Оригинальный план | 🔲 Моя модификация |
| Демо-вау | ✅ «AI пишет и запускает код» | 🔲 Обычный API-вызов |
| Точность | ⚠️ LLM может перепутать границы | ✅ Тестированный код |
| Латентность | ⚠️ 10-30 сек | ✅ 2-5 сек |
| Cost | ⚠️ $0.10+ / запрос | ✅ $0.01-0.05 |

**Критический аргумент:** formulas простые (`balance / avg_daily_sales`, сравнение периодов) — LLM воспроизведёт по reference без ошибок. Self-correction страхует. Графики и демо-эффект перевешивают латентность для пилота.

### Митигация рисков CI-подхода

| Риск | Митигация |
|------|-----------|
| LLM перепутает границы периодов | В SKILL.md — чёткие формулы; в reference — рабочий код; few-shot пример |
| Sandbox упадёт / timeout | Retry в LangGraph node; fallback на function calling для критичных |
| Данные ушли в OpenAI | Parquet без PII (нет имён клиентов, только product_code + rating) |
| Cost при частых запросах | File upload один раз; prompt caching для system prompt |

---

## 5. Ключевые интерфейсы

### 5.1 API

```http
GET  /health                                     → {status: "ok"}

POST /api/v1/sync/1c                             → синхронизация из 1С (balances, products)
POST /api/v1/datasets/import                     → загрузка Excel-выгрузок

POST /api/v1/analyses                             → создать анализ
     body: {question: "Почему снизились продажи..."}
     → {analysis_id, status: "waiting_for_approval", plan: {...}}

GET  /api/v1/analyses/{id}                       → получить статус + план/результат

POST /api/v1/analyses/{id}/approve               → запустить выполнение
POST /api/v1/analyses/{id}/revise               → пересобрать план
POST /api/v1/analyses/{id}/reject                → отменить

POST /api/v1/reports/management                  → авто-отчёт (fixed workflow)
     → {report_id, sections: [...]}
```

### 5.2 AnalysisPlan (контракт между planner и executor)

```python
class AnalysisPlan(BaseModel):
    question: str
    product_codes: list[str]
    period: PeriodConfig           # current_days, comparison
    skill: Literal[
        "sales-decline-analysis",
        "inventory-planning",
        "portfolio-growth",
        "reviews-and-pricing",
    ]
    hypotheses: list[Hypothesis]   # id, title, datasets, method
    limitations: list[str]
```

### 5.3 Skills (инструкции для Code Interpreter)

Каждый `SKILL.md` — это текстовая инструкция, которую `select_skill` node инжектит в system prompt CI. Не runtime-код — **prompt engineering**.

```markdown
# Skill: sales-decline-analysis

## Когда применять
Вопрос содержит «почему снизились продажи», «упали продажи», «падение продаж».

## Что анализировать
Проверь 5 гипотез по утверждённому плану:
- H1: Дефицит остатков — balance = 0 или < 20
- H2: Рост негативных отзывов (WB и Ozon отдельно)
- H3: Падение категории (productType)
- H4: Падение портфеля Mirrolla
- H5: Изменение цены — данных нет, отметь как limitation

## Как считать (reference)
См. reference code: compare_periods, analyze_decline
Период: текущие 14 дней vs предыдущие 14 дней.
Ключ: product_code (ЦБ-XXXXXXXX / ФР-XXXXXXXX).

## Формат ответа
- verdict: «Продажи снизились на X%»
- Для каждой гипотезы: confirmed True/False/None + detail
- likely_cause: подтверждённые гипотезы
- limitations: что не проверено
- График: orders по дням (текущий vs предыдущий период)
```

4 SKILL.md файла (Day 2):
- `skills/sales-decline-analysis/SKILL.md`
- `skills/inventory-planning/SKILL.md`
- `skills/portfolio-growth/SKILL.md`
- `skills/reviews-and-pricing/SKILL.md`

### 5.4 Data model (в памяти, без БД)

| DataFrame | Источник | Колонки | Размер |
|-----------|----------|---------|--------|
| `ozon` | 3 xlsx | product_code, sku_ozon, product_name, order_id, order_status, date, rating, review_text | 170K строк |
| `wb_reviews` | 1 xlsx | review_id, date, product_code, rating, brand, review_text, pros, cons, gtin | 4K строк |
| `balances` | 1С API | product_code, name, balance | ~3.8K строк |
| `products` | 1С JSON | product_code, catalog_name, product_type, brand, gtin | 3.8K строк |

**Нет PostgreSQL, нет Parquet, нет Redis.** 170K строк Ozon + 4K WB — в памяти pandas (~200 MB). SQLite — только для HITL checkpointer state.

---

## 6. Альтернативы, рассмотренные и отклонённые

### A1. Function Calling вместо Code Interpreter → отклонён
- Только 8 предопределённых функций — нет гибкости для ad-hoc вопросов
- Нет self-correction — упал → ошибка пользователю
- Нет графиков «из коробки»
- Демо-эффект слабее («обычный API-вызов» vs «AI пишет и запускает код»)
- **Вернуть как fallback** если CI sandbox недоступен на демо

### A2. PostgreSQL + Parquet как хранилище (оригинальный roadmap) → отклонён для MVP
- Данные помещаются в памяти (170K строк)
- PostgreSQL — лишний сервис в Docker Compose
- **Parquet возвращается** как формат для загрузки в Code Interpreter (Parquet files → OpenAI Files API)
- **PostgreSQL вернуть в Phase 2** при росте объёма или многопользовательском режиме

### A3. Ollama (локальная модель) → отклонён
- Code Interpreter работает только с OpenAI
- Локальная модель слабее пишет Python
- VPN + 1С уже на машине разработчика — ещё и GPU оверлокально
- **Вернуть в Phase 2** для cost reduction и data privacy

### A4. RAG (векторный поиск по отзывам/описаниям) → отложен
- 6 типов вопросов — структурированные, не семантический поиск
- Skills + helpers покрывают все 6 вопросов
- RAG нужен для свободных вопросов («расскажи про шампуни»)
- **Вернуть в Phase 2** для расширения функциональности

### A5. Gradio вместо Streamlit → отклонён
- Streamlit лучше для чат-интерфейса + таблиц
- HITL форма (approve/revise) проще в Streamlit
- Оба поднимаются за 15 минут — но Streamlit ближе к финальному UX

---

## 7. Риски и митигации

| Риск | Вероятность | Impact | Митигация |
|------|-------------|--------|-----------|
| VPN упадёт на демо | Средняя | Высокий | Pre-fetch balances+products в JSON перед демо; fallback на cached data |
| gpt-4o выбирает неправильный skill | Низкая | Средний | 4 skills с чётким описанием; few-shot примеры в system prompt |
| LLM галлюцинирует числа в ответе | Средняя | Высокий | LLM получает structured results от helpers; инструкция: «не придумывай числа» |
| HITL state теряется (SQLite) | Низкая | Средний | Volume для sqlite в Docker; auto-restore на перезапуске |
| Файлы Ozon пересекаются по датам (дубли) | Подтверждено | Низкий | `drop_duplicates(subset=["order_id", "product_code"])` — уже реализовано |
| 1С ProductSales отдаёт 0 за все дни | Подтверждено | Средний | Тестовые данные Ozon (170K заказов) как основной источник продаж |
| Дата в 1С: ГГГГММДД, не ISO | Подтверждено | Низкий | `OneCClient.get_sales` уже конвертирует; валидация в schema |
| Дедлайн (2 дня) | Высокая | Высокий | Порядок сокращения: SEO → графики → edit гипотез → история → цена → WB/Ozon split |

### Главный риск: качество reasoning

LLM может выдать план, который не имеет смысла (например, «проверить остатки» для товара, которого нет в 1С). Митигация: **few-shot prompts** с реальными примерами из `decisions.md` + валидация `product_code` в `understand_node` перед планированием.

---

## 8. План доставки (Days 2-3)

### Day 2 — Agent + Skills + HITL (зеленая часть)

| # | Задача | Время | Артефакт |
|---|--------|-------|----------|
| 1 | `requirements.txt`: langgraph, langchain-openai, openai, pydantic, fastapi, uvicorn, streamlit, pyarrow | 15 мин | requirements.txt |
| 2 | `data/prepared/*.parquet`: нормализовать Ozon, WB, balances в Parquet для CI | 1 час | 4 parquet files |
| 3 | `agent/schemas.py`: AnalysisPlan, Question, Answer (Pydantic) | 30 мин | schemas.py |
| 4 | `skills/*/SKILL.md`: 4 skill-файла — инструкции для CI system prompt | 1.5 часа | 4 SKILL.md |
| 5 | `agent/graph.py`: StateGraph с 6 nodes + interrupt | 1.5 часа | graph.py |
| 6 | `agent/nodes.py`: understand, select_skill, plan, execute_ci, synthesize | 2 часа | nodes.py |
| 7 | `agent/ci_runner.py`: file upload + prompt assembly + run + extract results | 2 часа | ci_runner.py |
| 8 | Smoke test: вопрос «Почему снизились продажи ЦБ-...?» → план → approve → ответ | 1 час | работает |

**Критерий готовности Day 2:** цепочка вопрос → гипотезы → подтверждение → CI пишет код → ответ работает в CLI (без UI).

### Day 3 — API + UI + Report + Docker (упаковка)

| # | Задача | Время | Артефакт |
|---|--------|-------|----------|
| 1 | `api/main.py`: FastAPI с 8 эндпоинтами | 1.5 часа | main.py |
| 2 | `ui/streamlit_app.py`: чат + HITL форма + таблицы | 2 часа | streamlit_app.py |
| 3 | `reports/generator.py`: авто-отчёт (fixed workflow, Jinja2 → HTML) | 1 час | generator.py |
| 4 | `compose.yaml` + `Dockerfile`: api + ui | 1 час | compose.yaml |
| 5 | `.env.example` + `README.md` | 1 час | .env.example, README.md |
| 6 | Демо: `docker compose up` с нуля | 30 мин | работает |
| 7 | Запись скринкаста 2 мин | 30 мин | demo.mp4 |

**После середины Day 3** — новые функции не добавляем.

### Порядок сокращения (если не успеваем)

1. ~~SEO-аудит~~ (уже нет в scope)
2. Генерация сложных графиков
3. Редактирование отдельных гипотез через форму
4. Сохранение истории анализов
5. Разделение WB/Ozon во всех сценариях
6. Авто-отчёт (если совсем туго — статичный HTML)

**Обязательно остаётся:** 1С · анализ падения · остатки · производственный план · топ роста/падения · негативные отзывы · один HITL · Docker · README.

---

## 9. Видение 12 месяцев (кратко, для ТЗ №4)

```
Phase 1 (MVP, сейчас)      Phase 2 (3 мес)           Phase 3 (6-12 мес)
─────────────────         ─────────────────         ──────────────────
gpt-4o + helpers           + Code Interpreter        + Multi-agent
LangGraph + SQLite         + PostgreSQL              + Langfuse/MLflow
Streamlit (1 user)         + Gradio (multi-user)     + Web app (React)
Function calling           + RAG (Qdrant)            + Hybrid search
4 skills                   + Ad-hoc analysis         + Custom skills
Excel + 1С VPN             + 1С staging API          + 1С production
                           + Scheduler (daily)        + Alerts (Telegram)
                           + Eval (RAGAS)            + Feedback loop (DPO)
```

### Стек 12 месяцев

| Слой | MVP | Phase 2 | Phase 3 |
|------|-----|---------|---------|
| LLM | OpenAI gpt-4o | + local Llama 3.1 8B | vLLM для батчинга |
| Orchestration | LangGraph + SQLite | LangGraph + PostgreSQL | LangGraph + Temporal |
| Vector DB | — | Qdrant | Qdrant + reranker |
| OLAP | pandas in-memory | DuckDB | ClickHouse |
| Observability | print() | MLflow tracing | Langfuse + Grafana |
| UI | Streamlit | Gradio | React + FastAPI |
| Deploy | Docker Compose | Docker Compose | K8s |

### Оборудование (MVP)

- **CPU:** 4 vCPU (любой современный)
- **RAM:** 16 GB (pandas 170K строк + gpt-4o API)
- **GPU:** не требуется (OpenAI hosted)
- **Storage:** 5 GB (xlsx + JSON + SQLite)
- **Network:** VPN к 1С + доступ к OpenAI API

### Оборудование (12 месяцев, on-prem для локальной модели)

- **GPU:** 2× RTX 4090 24GB (Llama 3.1 8B + embedding model)
- **CPU:** 32 vCPU
- **RAM:** 128 GB
- **Storage:** 2 TB NVMe
- **Cost:** ~$15-20k capex (одноразово)

---

## 10. Открытые вопросы

| # | Вопрос | Когда решать |
|---|--------|--------------|
| Q1 | Должен ли авто-отчёт выгружаться в Excel/PDF или достаточно HTML в UI? | Day 3 |
| Q2 | Нужна ли авторизация в UI (1 менеджер = 1 логин) или это локальный инструмент? | MVP: нет |
| Q3 | Как часто синхронизировать 1С? On-demand (по кнопке) или по расписанию? | MVP: on-demand |
| Q4 | Сохранять ли историю анализов между сессиями (SQLite checkpointer достаточно)? | MVP: да, SQLite |
| Q5 | OpenAI API key — храним в `.env` локально или нужен прокси (cost control)? | MVP: `.env` |

---

## Итог

**Что оптимизировано:** time-to-ship (2 дня до дедлайна) и демо-эффект (AI пишет и запускает код live).

**Чем пожертвовали:** точностью (LLM пишет код, а не вызывает протестированные функции), латентностью (10-30 сек на sandbox), cost ($0.10+ за запрос).

**Архитектура:** LangGraph оркеструет рассуждения и HITL. Code Interpreter выполняет анализ в sandbox. Skills (SKILL.md) + reference-код (helpers) идут в system prompt как инструкция. Parquet-файлы загружаются в OpenAI один раз.

**Fallback:** если CI недоступен на демо — `run_analytics.py` (детерминированный Python без LLM) формирует все 6 разделов отчёта. Агентная часть — надстройка, а не фундамент.