# Mirrolla AI — План реализации

> **Дата:** 2026-07-16
> **Подход:** функциональные майлстоны — каждый добавляет новую способность сервиса, тестируется независимо
> **Принцип:** усложнение логики по слоям. Не «что делать в день N», а «какая способность появляется у сервиса»

---

## Майлстоны

### M1 — Helpers (чистый Python, без LLM)

**Способность:** сервис считает аналитику по данным

| | |
|---|---|
| **Зависимости** | — |
| **Артефакты** | `helpers/sales.py`, `helpers/stocks.py`, `helpers/reviews.py`, `run_analytics.py` |
| **DoD** | `python run_analytics.py` печатает все 6 разделов в консоли |
| **Статус** | ✅ Готово |

---

### M2 — Router (классификация вопроса)

**Способность:** сервис понимает, **какой skill** нужен для ответа на вопрос менеджера

```
Вопрос → gpt-4o → {skill, product_codes, period}
```

| | |
|---|---|
| **Зависимости** | M1 (helpers как reference) |
| **Артефакты** | `agent/router.py`, `agent/schemas.py` (Question, RoutingResult) |
| **DoD** | `python -m agent.router "Почему упали продажи ЦБ-00007397?"` печатает `{skill: "sales-decline-analysis", product_codes: ["ЦБ-00007397"], period_days: 14}` |
| **Must** | 4 skill-класса распознаются по ключевым словам вопроса |
| **Could** | Router извлекает period_days из вопроса («за последний месяц» → 30) |

**Тесты (5 вопросов):**
```
"Почему упали продажи шампуня?"       → sales-decline-analysis
"Что заканчивается на складе?"        → inventory-planning
"Что растёт быстрее рынка?"           → portfolio-growth
"Какие отзывы плохие?"                → reviews-and-pricing
"Закажи производство репейного масла" → inventory-planning
```

---

### M3 — Planner (структурированный план)

**Способность:** сервис формирует **план анализа** — гипотезы, датасеты, метод

```
Вопрос + routing → gpt-4o → AnalysisPlan {
    skill, product_codes, period,
    hypotheses [{id, title, datasets, method}],
    limitations []
}
```

| | |
|---|---|
| **Зависимости** | M2 (routing result на вход) |
| **Артефакты** | `agent/planner.py`, `skills/*/SKILL.md` (4 файла-инструкции) |
| **DoD** | `python -m agent.planner "Почему упали продажи ЦБ-00007397?"` печатает JSON с 5 гипотезами, датасетами, limitations |
| **Must** | Planner читает SKILL.md выбранного skill'а и генерит план по его структуре |
| **Should** | Planner проверяет, что product_code реально существует в каталоге |
| **Could** | Planner предлагает альтернативные периоды (7 / 14 / 30 дней) |

---

### M4 — Executor (Code Interpreter)

**Способность:** сервис **выполняет анализ** — пишет и запускает Python-код в sandbox

```
AnalysisPlan → Code Interpreter → results (JSON) + charts (PNG)
```

| | |
|---|---|
| **Зависимости** | M1 (reference code), M3 (plan на вход) |
| **Артефакты** | `agent/executor.py`, `agent/ci_runner.py`, `data/prepared/*.parquet` (4 файла) |
| **DoD** | `python -m agent.executor --plan tests/fixtures/plan_decline.json` печатает results + сохраняет PNG график |
| **Must** | CI читает Parquet, воспроизводит логику из reference code, возвращает JSON |
| **Should** | CI строит matplotlib график (orders по дням, текущий vs предыдущий период) |
| **Could** | CI сам исправляет упавший код (self-correction, до 3 retry) |

**Принцип работы CI:**
```
system_prompt = SKILL.md + helpers reference code + dataset schema + plan
→ LLM пишет: df = pd.read_parquet("ozon.parquet")
             # сравнивает периоды, считает гипотезы
             # строит график
→ sandbox запускает → results + PNG
```

**Это главный риск-майлстон.** Если CI не взлетает — fallback: executor вызывает helpers напрямую (function calling), CI отложить на Phase 2.

---

### M4.5 — Reporter (LLM-синтез ответа)

**Способность:** сервис **формирует человекочитаемый ответ** менеджеру на основе структурированных findings от Executor

```
findings (CI) + question + skill → Reporter LLM (gpt-4o) → markdown-ответ менеджеру
```

| | |
|---|---|
| **Зависимости** | M4 (executor с findings контрактом) |
| **Артефакты** | `agent/reporter.py` (synthesize + fallback), обновлённый `schemas.py` (Finding модель) |
| **DoD** | `python -m agent.executor "какие товары заканчиваются?"` печатает findings + markdown-ответ с конкретными товарами, артикулами, цифрами, рекомендациями |
| **Статус** | ✅ Готово |
| **Must** | Finding модель в schemas: entity_type, entity_id, name, priority, reasons, metrics, recommended_action |
| **Must** | Универсальный контракт `findings` в CI prompt (UNIVERSAL_ANALYSIS_INSTRUCTIONS) — CI возвращает список объектов, не счётчики |
| **Must** | Reporter LLM (gpt-4o) берёт findings + question → формирует ответ: краткий итог + топ-N объектов с артикулом/названием/причиной/действием |
| **Must** | Семантическая валидация: для list-вопросов findings не пустой, каждый finding имеет entity_id и reasons; retry если пустой |
| **Should** | 4 SKILL.md дополнены секциями «Единица анализа», «Метрики», «Классификация priority», «findings формат» |
| **Should** | Fallback: если LLM недоступен — шаблонный ответ из findings (без API) |
| **Could** | NaN/inf sanitization в парсере (metrics → None, reasons «nan» → «N/A») |

**Принцип:** CI = фактура (считает), Reporter = интерпретация (объясняет менеджеру). Разделение ответственности: CI не пишет «красивый текст», Reporter не считает.

---

### M5 — HITL (человек в цикле)

**Способность:** сервис **останавливается перед выполнением** и ждёт подтверждения

```
Plan → interrupt(approve/revise/reject) → executor → reporter → answer
```

| | |
|---|---|
| **Зависимости** | M3 (plan), M4 (executor), M4.5 (reporter) |
| **Артефакты** | `agent/graph.py` (LangGraph StateGraph), `agent/nodes.py` |
| **DoD** | `python -m agent "Почему упали продажи ЦБ-00007397?"` печатает план, ждёт ввода `approve` в консоли, выполняет, печатает ответ (от Reporter LLM) |
| **Must** | LangGraph StateGraph: understand → route → plan → interrupt → execute → report |
| **Must** | SQLite checkpointer (состояние сохраняется между запусками) |
| **Should** | revise: менеджер правит период / product_code → пересобрать план |
| **Could** | reject: отменить анализ без выполнения |

| **Статус** | ✅ Готово |

---

### M6 — API (FastAPI)

**Способность:** сервис доступен через **HTTP эндпоинты**

```
POST /api/v1/analyses        → создаёт анализ, возвращает plan
POST /api/v1/analyses/{id}/approve → запускает выполнение
GET  /api/v1/analyses/{id}   → статус + результат
POST /api/v1/reports/management → авто-отчёт
```

| | |
|---|---|
| **Зависимости** | M5 (LangGraph workflow) |
| **Артефакты** | `api/main.py` |
| **DoD** | `curl -X POST localhost:8000/api/v1/analyses -d '{"question":"..."}'` возвращает analysis_id + plan. `curl -X POST .../approve` запускает и возвращает результат |
| **Must** | 5 эндпоинтов: analyses (create, get, approve, revise, reject) |
| **Should** | `POST /api/v1/reports/management` — fixed workflow авто-отчёта |
| **Could** | `POST /api/v1/sync/1c` — синхронизация из 1С по кнопке |

| **Статус** | ✅ Готово |

---

### M7 — UI (Streamlit)

**Способность:** менеджер работает с ассистентом **через браузер**

```
Браузер → чат → план → кнопка [Approve] → ответ + таблицы + графики
```

| | |
|---|---|
| **Зависимости** | M6 (API) |
| **Артефакты** | `ui/streamlit_app.py` |
| **DoD** | Открыть `localhost:8501` → написать вопрос → увидеть план → нажать Approve → получить ответ с таблицей и графиком |
| **Must** | Чат-интерфейс + HITL форма (approve / revise / reject) |
| **Must** | Таблицы с результатами (top-10, critical stocks, ...) |
| **Should** | Графики (PNG из CI) отображаются в чате |
| **Could** | История анализов в боковой панели |

| **Статус** | ✅ Готово |

---

### M8 — Auto-report + Docker + Demo

**Способность:** сервис **запускается одной командой** и формирует авто-отчёт

```
docker compose up → всё работает → авто-отчёт по кнопке
```

| | |
|---|---|
| **Зависимости** | M6 (API), M7 (UI) |
| **Артефакты** | `reports/generator.py`, `compose.yaml`, `Dockerfile`, `.env.example`, `README.md` |
| **DoD** | С чистого окружения: `docker compose up --build` → localhost:8501 работает → авто-отчёт формируется |
| **Must** | `compose.yaml` (2 сервиса: api + ui), Dockerfile, README с инструкцией |
| **Must** | Авто-отчёт: fixed workflow (топ-10 рост, топ-10 падение, критические остатки, негатив отзывы, рекомендации) |
| **Should** | Запись скринкаста 2 мин (демо) |
| **Could** | `.env.example` с описанием всех переменных |

---

## Зависимости

```
M1 (helpers) ✅
   │
   ├──► M2 (router)
   │       │
   │       └──► M3 (planner)
   │                │
   │                └──► M4 (executor) ◄── M1 (reference)
   │                         │
   │                         └──► M4.5 (reporter LLM)
   │                                  │
   │                                  └──► M5 (HITL/graph)
   │                                           │
   │                                           └──► M6 (API)
   │                                                   │
   │                                                   └──► M7 (UI)
   │                                                           │
   │                                                           └──► M8 (Docker + report + demo)
   │
   └──► M4 (reference code для CI system prompt)
```

**Линейный путь:** M1 → M2 → M3 → M4 → M4.5 → M5 → M6 → M7 → M8

**Параллельное:** M2 + M3 можно делать параллельно с подготовкой Parquet для M4.

---

## Cut sequence (что отрезать, если не успеваем)

В обратном порядке от конца:

| # | Что режем | Impact |
|---|-----------|--------|
| 1 | M7 could: история анализов в UI | Минимальный |
| 2 | M8 should: скринкаст демо | Минимальный (можно live-демо) |
| 3 | M5 could: reject (оставить approve + revise) | Низкий |
| 4 | M6 should: авто-отчёт (оставить chat-only) | Средний |
| 5 | M4 should: графики (таблицы без графиков) | Средний |
| 6 | M6 could: /sync/1c (1С только через CLI) | Низкий |

**Нельзя отрезать:** M1, M2, M3, M4 Must, M4.5 Must, M5 Must, M6 Must, M7 Must, M8 Must (Docker + README).

**Hard fallback:** если M4 (Code Interpreter) не взлетает — executor вызывает helpers напрямую (function calling). Демо-эффект слабее, но логика та же.

---

## Риски по майлстонам

| Майлстон | Риск | Митигация |
|----------|------|-----------|
| M2 | Router путает inventory-planning и sales-decline | Few-shot примеры в system prompt |
| M3 | Planner генерит гипотезы, непокрываемые данными | SKILL.md содержит список доступных датасетов |
| **M4** | **CI пишет код с ошибками** | **Reference code в prompt + self-correction + fallback на function calling** |
| **M4** | **CI timeout / sandbox недоступен** | **Retry 3×, fallback на helpers** |
| **M4.5** | **Reporter LLM галлюцинирует данные** | **REPORTER_PROMPT: «не придумывай отсутствующие данные», fallback шаблон** |
| **M4.5** | **CI возвращает NaN / усечённый JSON** | **Sanitize NaN→None, // comment removal, max_output_tokens=16000** |
| M5 | LangGraph interrupt не работает с SQLite | Использовать MemorySaver для demo |
| M6 | API blocking executor (10-30 сек) | Background task + polling |
| M8 | Docker на Windows ломается | .dockerignore, volume paths через `${PWD}` |