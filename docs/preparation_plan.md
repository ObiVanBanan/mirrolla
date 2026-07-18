# План подготовки к пилотному заданию Mirrolla (AI Engineer)

> **Источник:** Анализ Obsidian Vault (`C:\Users\theso\Documents\Obsidian Vault`) + детальное ТЗ (`tz.md`) + roadmap (`roadmap.md`)
> **Дата:** 2025-07-14
> **Срок:** 5 рабочих дней

---

## 📋 Кратко по ТЗ (из `tz.md` + `roadmap.md`)

| Задача | Суть | Ключевые технологии из ТЗ |
|--------|------|---------------------------|
| **№1 AI-ассистент** | Чат-бот для 6 типов вопросов: падение продаж, остатки, производство, рост vs рынок, отзывы, цены | LangGraph + OpenAI Code Interpreter + Code Interpreter / Python Tool Use, HITL (Human-in-the-loop) |
| **№2 Аналитический модуль** | Авто-отчёт: топ-10 рост/падение, критические остатки, негатив отзывы, рекомендации | Python/Pandas/Parquet, helper-функции, Jinja2/HTML/PDF |
| **№3 Интеграция с 1С** | Mock/Real API: товары, остатки, продажи через OData/HS (`WebAssistant`) | `httpx` + OAuth/Basic Auth, инкрементальная синхронизация, Pydantic модели |
| **№4 Архитектурный док** | ≤5 стр.: Vision 12 мес, стек, риски, roadmap, железо | System Design, MLOps/LLMOps, Cost estimation |

**Делабери:** Исходный код + `docker compose up` + `README.md` + демо (видео/скринкаст) + `ARCHITECTURE.md`

---

## ✅ ЧЕК-ЛИСТ: Темы, которые УЖЕ ЕСТЬ в Obsidian (нужно ПОВТОРИТЬ / ПОДТЯНУТЬ)

> Стиль: как в `MOC — Память и RAG для ИИ-агентов.md` и `Трёхуровневая архитектура агента.md` — кратко, со ссылками на файлы.

### 🧠 LLM / RAG / Agent Architecture — **СИЛЬНАЯ СТОРОНА**

| Тема в Obsidian | Файл / Skill | Что повторить под ТЗ |
|-----------------|--------------|----------------------|
| **Трёхуровневая архитектура агента** (Runtime / Agent / Service Layer) | `Трёхуровневая архитектура агента.md` | **Ключевое для ТЗ №4** — именно эта архитектура просится в архитектурном доке. Повтори: протоколы (`Protocol`), Runtime (таймауты, фоллбеки), Service Layer (LLM, Vector DB, Cache). |
| **MOC — Память и RAG для ИИ-агентов** | `MOC — Память и RAG для ИИ-агентов.md` | Карта понятий: Session Memory, Long-term Memory, Vector DB, GraphRAG, Hybrid Search, Mem0, Zep, LangGraph Store. Для ТЗ №1 (RAG по выгрузкам WB/Ozon/Отзывы/1С) — ядро. |
| **MVP RAG система (OpenAI)** | `Проекты/MVP RAG система/RAG Система с OpenAI.md` | Твой рабочий RAG на OpenAI — база для ТЗ №1. Добавь: hybrid search, reranker, фильтрация по метаданным (SKU, marketplace, date, warehouse). |
| **Трёхэтапный цикл RAG** (extract → generate → save) | в MOC | Для ТЗ №2 (авто-отчёт): retrieve sales/reviews → LLM суммаризация → сохранение отчёта в память/БД. |
| **Hybrid Search + фильтрация по скалярам** | в MOC | **Критично для ТЗ №1**: фильтрация по `marketplace`, `sku`, `warehouse`, `date_range` + семантический поиск по отзывам/описаниям. |
| **RAG Demo Corpus Curation** | skill `rag-demo-corpus-curation` | Подготовка демо-корпуса 5–10 доков — пригодится для демо ТЗ. |
| **LLM Wiki / Karpathy LLM Wiki** | skill `llm-wiki` | Быстрая навигация по LLM-темам при необходимости. |

### 🛠️ Agentic / Tool Use / Function Calling — **СИЛЬНАЯ СТОРОНА**

| Тема | Файл / Skill | Что повторить |
|------|--------------|---------------|
| **Tool Use / Function Calling** | `Tool Use (инструменты).md`, `Tool-calling.md` | **Ключево для ТЗ №1 и №3**: JSON Schema для tools, parallel tool calls, structured output (Pydantic), retry/fallback логика. |
| **LangGraph как stateful orchestration layer** | `LangGraph как stateful orchestration layer.md` | **Ключево для ТЗ №1 и №4**: StateGraph, nodes/edges, checkpointers (PostgresSaver), interrupts для HITL, streaming (`astream`/`astream_log`), subgraphs, recursion limit. |
| **ReAct / Reflexion / Planning** | `Reflection (критик).md`, `Planning (планирование).md` | Для ТЗ №1: агент планирует цепочку вызовов (продажи → остатки → отзывы → синтез ответа). Повтори ReAct pattern. |
| **Агентная система для ML задач** | `Проекты/Агнетная система для ML задач.md` | Твой проект — отличная база для архитектурного дока ТЗ №4. |

### 🛠️ Engineering / DevOps / MLOps — **ЕСТЬ БАЗА**

| Тема | Файл / Skill | Что повторить |
|------|--------------|---------------|
| **Docker Compose локальный стек** | skill `docker-local-dev-stack` | **Обязательно для ТЗ**: `docker-compose.yml` с Postgres, Redis, Qdrant/Chroma, FastAPI, Ollama/vLLM, Grafana/Prometheus. Есть скилл — повтори команды. |
| **FastAPI soft error responses** | skill `fastapi-soft-error-responses` | Паттерн: HTTP 200 + JSON `{error: {...}}` — удобно для LLM-агентов, не падать на 500. |
| **Python logging с Rich** | skill `python-logging-setup`, `rich-logging-migration` | Красивые логи для демо и дебага. |
| **Postgres migrations pitfalls** | skill `postgres-migration-pitfalls` | Для ТЗ №3 (mock 1С → Postgres) — миграции продаж/остатков/отзывов. |
| **CSV → Postgres migration** | skill `csv-postgres-migration` | **Прямо для ТЗ**: выгрузки WB/Ozon (CSV/Excel) → Postgres. Есть скилл — повтори паттерн. |
| **Docker Windows → Linux build debugging** | skill `docker-windows-to-linux-build-debugging` | Ты на Windows, деплой в Docker (Linux) — этот скилл спасёт от боли с путями/line endings. |
| **Production Readiness Audit** | skill `production-readiness-audit` | Чек-лист для ТЗ №4 (раздел «Готовность к продакшену»). |
| **MLflow GenAI Evaluation** | skill `mlflow-genai-evaluation` | Для ТЗ №4 (раздел «Оценка качества / мониторинг»). MLflow Evaluate для LLM-as-judge. |
| **MLflow Tracing / Instrumenting** | skills `mlflow-instrumenting-tracing`, `mlflow-retrieving-traces` | Трейсинг LLM-цепочек — для observability в ТЗ №4. |

### 📊 Data / Analytics / SQL — **ЕСТЬ БАЗА**

| Тема | Файл / Skill | Что повторить |
|------|--------------|---------------|
| **Pandas основы** | `Pandas основы.md` | Для ТЗ №2 (аналитика: топ-10 рост/падение, остатки, отзывы) — Pandas / Polars / DuckDB / SQL. |
| **Multi-source ETL Sync** | skill `multi-source-etl-sync` | **Прямо для ТЗ №1, №2, №3**: ETL из CSV (WB, Ozon) + API (1С) + Отзывы → единая БД. Есть скилл — повтори паттерн. |
| **Database Schema Research** | skill `database-schema-research` | Разведка схемы БД выгрузок WB/Ozon/1С. |
| **Data Completeness Filler** | skill `data-completeness-filler` | Sparse атрибуты товаров (SEO, характеристики) — заполнение через LLM. Для ТЗ №1 (SEO карточек). |
| **CSV Mapping Pipeline** | skill `csv-mapping-pipeline` | Маппинг колонок выгрузок WB/Ozon/1С в единую схему. |

### 🧠 ML / NLP Fundamentals — **ОЧЕНЬ СИЛЬНАЯ БАЗА** (повторить только слабые места)

> Файлы в `Обучение/` — огромная база. Повторять только то, что «забыл/заплыл».

| Тема | Файлы в `Обучение/` |
|------|---------------------|
| **Embeddings / Embedding Layer** | `Эмбеддинги.md`, `Обучаемый embedding layer.md`, `Как обучается embedding layer.md` |
| **Transformer / Attention / MHA / RoPE / KV-Cache** | `Transformer.md`, `Self-attention vs cross-attention.md`, `Multi-head attention.md`, `Scaled dot-product зачем делить на √d.md`, `Positional encoding.md`, `Causal mask.md`, `Feed-forward block в трансформере.md`, `Residual connections.md`, `LayerNorm.md` |
| **LLM / Decoder-only / Next-token prediction** | `LLM.md`, `Decoder-only.md`, `Next-token prediction.md` |
| **Tokenization (BPE, WordPiece, SentencePiece)** | `BPE - идея и компромисс.md`, `WordPiece.md`, `SentencePiece.md`, `Subword tokenization.md`, `Token type, vocabulary, OOV.md` |
| **RAG / Retrieval / Reranking** | `Зачем вообще нужен retrieval.md`, `Hybrid search.md`, `Re-ranking.md`, `Косинусное сходство.md`, `Когда cosine лучше L2 для текста.md` |
| **LoRA / PEFT** | `LoRA.md` |
| **RNN / Attention history** | `Что такое RNN.md`, `Attention.md` |

> **Вердикт:** ML-фундамент **очень сильный**. Повторять только KV-cache, RoPE, FlashAttention нюансы, quantization (GGUF/GPTQ/AWQ) для ТЗ №4 (железо).

---

## 🔴 ЧЕК-ЛИСТ: Тем, которых НЕТ в Obsidian (НУЖНО ИЗУЧИТЬ С НУЛЯ / ГЛУБОКО ПОДТЯНУТЬ)

### 🔴 ТЗ №1: AI-Ассистент для менеджеров маркетплейсов (RAG + Agent + Tool Use)

| Тема | Что конкретно изучить | Ресурсы / Skills |
|------|----------------------|------------------|
| **Function Calling / Tool Use с OpenAI / Ollama / vLLM** | JSON Schema для tools, parallel tool calls, parallel function calling, structured output (Pydantic), retry/fallback логика | OpenAI Function Calling docs, `tool-calling` skill, `openai-multimodal-api-integration` skill |
| **LangGraph Production Patterns** | StateGraph с checkpointer (PostgresSaver / SQLiteSaver), interrupts для HITL, streaming (`astream` / `astream_log`), subgraphs, recursion limit, error handling в узлах | LangGraph docs, `langgraph` skill (есть в available skills) |
| **Hybrid Search (Vector + BM25 + Metadata Filters)** | Qdrant / Chroma / PGVector: hybrid search + filter по `marketplace`, `sku`, `warehouse`, `date_range`. Reranker (Cohere Rerank / bge-reranker / jina-reranker) | `hybrid-search` в MOC, Qdrant/Chroma docs, `rag-retrieval-evaluation` skill |
| **RAG Evaluation (RAGAS / MLflow Evaluate)** | Faithfulness, Answer Relevancy, Context Precision/Recall, LLM-as-judge | `rag-retrieval-evaluation`, `mlflow-genai-evaluation`, `rag-evaluation-llm-as-judge` skills |
| **Agentic RAG / Multi-hop QA** | Декомпозиция вопроса → подзапросы → параллельный retrieve → синтез ответа. Пример: «Почему упали продажи SKU-123?» → продажи + остатки + отзывы + цены конкурентов → синтез | LangGraph Agentic RAG tutorials, `llm-agent-evaluation` skill |
| **Structured Output / Pydantic + Instructor** | Pydantic модели для ответа агента (структурированный JSON: `answer`, `sources`, `confidence`, `actions[]`) | `instructor` lib, `openai-multimodal-api-integration` skill |
| **Streaming UX (SSE / WebSocket)** | Токен-поток в UI, thinking process streaming | FastAPI SSE, `realtime-audio-websocket` skill (паттерны WS) |

### 🔴 ТЗ №2: Аналитический модуль (Auto-Reporting)

| Тема | Что изучить |
|------|-------------|
| **OLAP / Analytical DB для продаж** | DuckDB / ClickHouse / Apache Druid для быстрых агрегаций по 3 мес. данным. DuckDB — проще для MVP (in-process, Parquet/CSV). |
| **Time-series Analysis для продаж** | Rolling averages, YoY/MoM, trend detection (Mann-Kendall, Prophet, или простой slope), seasonality detection. |
| **Inventory Analysis** | Days of Stock (DOS), Stockout Risk, Reorder Point (ROP), EOQ basics. ABC/XYZ анализ SKU. |
| **Review Sentiment / Aspect-Based Sentiment Analysis (ABSA)** | Аспектный анализ отзывов: «качество», «доставка», «размер», «цвет». Ru/En модели: `rubert-tiny-sentiment`, `bert-base-multilingual-uncased-sentiment`, или LLM-as-judge. |
| **Price Elasticity / Competitor Price Tracking** | Простая эластичность: `%ΔQ / %ΔP`. Competitor price index. |
| **Automated Report Generation** | Jinja2 / WeasyPrint (PDF) или HTML-отчёт. LLM-суммаризация: «Топ-3 инсайта за неделю». |
| **Scheduling (Cron / APScheduler / Airflow / Dagster)** | Ежедневный/еженедельный отчёт. Для MVP — APScheduler или cronjob skill. |

### 🔴 ТЗ №3: Интеграция с 1С (Mock API)

| Тема | Что изучить |
|------|-------------|
| **Mock API Server для 1С** | `httpx-mock` / `pytest-httpx` / `respx` / `wiremock` / простой FastAPI мок с JSON-fixtures. Нужно для CI/CD и демо. |
| **1С OData / REST API паттерны** | Обычные эндпоинты: `/goods`, `/stocks`, `/sales`, `/orders`. Пагинация (`$top`, `$skip`), фильтры (`$filter`), `$select`. OAuth / Basic Auth. |
| **ETL: 1С API → Postgres / DuckDB** | Incremental sync (по `modified_at`), upsert (ON CONFLICT), идемпотентность, retry с backoff, dead letter queue. |
| **Data Contracts / Schema Registry** | Pydantic модели для 1С ответов → валидация при ingest. `pydantic-xml` если 1С отдаёт XML. |

### 🔴 ТЗ №4: Архитектурный документ (≤5 стр.) — System Design / MLOps / LLMOps

| Раздел ТЗ | Что изучить / подготовить |
|-----------|---------------------------|
| **Видение через 12 месяцев** | LLM Platform Evolution: RAG → Agentic RAG → Multi-Agent → Self-Improving Agents. RAGOps / LLMOps maturity model. |
| **Технологический стек** | **LLM**: Ollama / vLLM / TGI / OpenAI-compatible. **Orchestration**: LangGraph / Temporal. **Vector DB**: Qdrant / PGVector / Chroma. **OLAP**: DuckDB / ClickHouse. **Orchestration/ETL**: Airflow / Dagster / Prefect. **Observability**: MLflow / Langfuse / LangSmith / Grafana+Loki. **Infra**: Docker Compose (MVP) → K8s (12 мес). **CI/CD**: GitHub Actions / GitLab CI. |
| **Риски** | LLM Cost / Latency, Hallucinations, Data Freshness (ETL lag), Vendor Lock-in (OpenAI vs Local), PII/GDPR (отзывы, PII в 1С), Model Drift, Prompt Injection, Prompt Leakage. |
| **Приоритеты (First 3 months)** | 1) RAG по выгрузкам + 1С API (MVP ассистент). 2) Ежедневный авто-отчёт. 3) Eval pipeline (RAGAS/MLflow). 4) Observability (traces, costs, latency). 5) Feedback loop (RLHF / DPO на логах). |
| **Оценка железа (12 мес)** | **GPU**: 2× H100 80GB или 4× A100 80GB (для 70B quantized / 8B full precision). **CPU**: 64+ vCPU. **RAM**: 256+ GB. **Storage**: 4+ TB NVMe (vector DB + OLAP + logs). **Network**: 10 Gbps. **Cost estimate**: ~$3-5k/mo cloud (AWS/GCP/Azure) или ~$50-80k capex on-prem. Для MVP (5 дней): 1× A10G / L4 (24GB) или 2× RTX 3090/4090 локально + 64GB RAM. |
| **Формат** | Markdown ≤5 стр. (≈2000 слов). Структура: Vision → Stack → Risks → Roadmap (Phases) → Hardware/Cost → Team/Roles. |

---

## 🟡 Темы, которые ЕСТЬ в Obsidian, но нужно ГЛУБОКО ПОДТЯНУТЬ под ТЗ

| Тема | Что конкретно подтянуть |
|------|------------------------|
| **Docker Compose Production-Ready** | Не просто `docker compose up`, а: healthchecks, `depends_on` с condition, resource limits, logging drivers, secrets (`.env`), networks, volumes, restart policies. Skill `docker-local-dev-stack` — доработать под продакшен-ready compose. |
| **PostgreSQL для продакшена** | Connection pooling (PgBouncer), партиционирование по дате (sales по месяцам), индексы (BRIN для time-series, GIN для JSONB), vacuum/analyze, replication. |
| **Vector DB Production (Qdrant / PGVector)** | HNSW параметры (m, ef_construct), quantization (scalar/binary), payload indexing, sharding, replication, backup/restore. |
| **LangGraph Checkpointing (PostgresSaver)** | Для production-агента — чекпоинты в Postgres, не в памяти. Migration схем чекпоинтов. |
| **Observability: MLflow + Langfuse / LangSmith** | Трейсинг LLM-цепочек, токены, латентность, стоимость, качество (LLM-as-judge). Skills `mlflow-instrumenting-tracing`, `mlflow-retrieving-traces`, `mlflow-querying-metrics`. |
| **CI/CD для AI (GitHub Actions)** | Линт (ruff), типы (mypy), тесты (pytest), build Docker, scan (trivy), deploy (compose / k8s). |
| **Testing LLM Apps** | `pytest` + `pytest-asyncio` + `httpx` (ASGI test client) + `instructor` для structured output тестов + `ragas` / `mlflow evaluate` для quality gates. |
| **Cost Estimation / Token Accounting** | Input/Output tokens per request, cost per 1k, caching (prompt caching, semantic cache), budget alerts. |
| **Prompt Engineering / DSPy** | Для ТЗ №1 (промпты агента) и №2 (промпты суммаризации отчёта). Skill `dspy` — декларативная оптимизация промптов. |
| **RAG Evaluation Pipeline (RAGAS / Custom)** | Skill `rag-retrieval-evaluation` — полный пайплайн: golden set → retrieval metrics → generation metrics. |

---

## 📅 План подготовки на 5 дней (параллельно с выполнением ТЗ)

> В стиле `roadmap.md` — с чекбоксами, критериями готовности, точками сокращения.

| День | Фокус | Задачи |
|------|-------|--------|
| **День 1** | **Инфраструктура + Data Ingestion** | 1. `docker-compose.yml` (Postgres, Qdrant, Redis, FastAPI, Ollama, Grafana/Prometheus). 2. ETL: CSV (WB/Ozon) + Mock 1С API → Postgres + Qdrant (embed товары + отзывы). 3. Pydantic модели данных. |
| **День 2** | **AI-Ассистент (ТЗ №1) — Core** | 1. LangGraph Agent: StateGraph с узлами `planner → retriever (hybrid) → tools (1C API) → synthesizer → responder`. 2. Function Calling для 1С API. 3. Structured Output (Pydantic). 4. Hybrid Search (Qdrant: vector + filter по SKU/маркетплейс/дата). |
| **День 3** | **AI-Ассистент (ТЗ №1) — Quality + UX** | 1. RAG Eval (RAGAS/MLflow): golden set 20-30 вопросов. 2. Streaming SSE ответ. 3. Simple UI (Streamlit / Gradio / FastAPI + HTML). 4. Few-shot промпты для каждого типа вопроса (6 типов из ТЗ). |
| **День 4** | **Аналитический модуль (ТЗ №2) + 1С Integration (ТЗ №3)** | 1. DuckDB / SQL аналитика: топ-10 рост/падение, DOS, отзывы (sentiment), цены. 2. Авто-отчёт (Jinja2 → HTML/PDF). 3. Scheduler (APScheduler/cronjob) ежедневный запуск. 4. Mock 1С API (FastAPI + JSON fixtures) + ETL sync. |
| **День 5** | **Архитектурный док (ТЗ №4) + Polish + Demo** | 1. Написать `ARCHITECTURE.md` (≤5 стр.). 2. `README.md` с инструкцией запуска (`docker compose up -d`). 3. Записать демо (asciinema / screen record). 4. Финальный прогон тестов, чистка логов. |

---

## 🎯 Контрольные точки сокращения (из `roadmap.md`)

Если не успеваем, вырезаем в таком порядке:

1. SEO-аудит.
2. Генерацию сложных графиков.
3. Редактирование отдельных гипотез через форму.
4. Сохранение полной истории анализов.
5. Точные рекомендации по цене.
6. Разделение анализа WB и Ozon во всех сценариях.

**Обязательно оставляем:**

- [x] 1С интеграция
- [x] Анализ падения продаж
- [x] Остатки
- [x] Производственный план
- [x] Топ роста и падения
- [x] Негативные отзывы
- [x] Отчёт
- [x] Один HITL checkpoint
- [x] Docker и README

---

## 🔗 Полезные Skills (уже есть в доступных) — загрузи по мере необходимости

| Skill | Когда загрузить |
|-------|-----------------|
| `docker-local-dev-stack` | День 1 (инфраструктура) |
| `csv-postgres-migration` | День 1 (ETL выгрузок) |
| `multi-source-etl-sync` | День 1-2 (WB + Ozon + 1С + Отзывы) |
| `langgraph` (есть в available) | День 2 (агент) |
| `rag-retrieval-evaluation` | День 3 (eval) |
| `mlflow-genai-evaluation` | День 3 (eval + tracing) |
| `mlflow-instrumenting-tracing` | День 3-4 (observability) |
| `production-readiness-audit` | День 4-5 (архитектурный док) |
| `scientific-report-writing` | День 5 (архитектурный док ≤5 стр.) |
| `rag-demo-corpus-curation` | День 1-2 (подготовка демо-данных) |
| `fastapi-soft-error-responses` | День 2 (API агента) |
| `python-logging-setup` / `rich-logging-migration` | День 1-2 (логирование) |
| `docker-windows-to-linux-build-debugging` | День 1 (ты на Windows) |
| `csv-mapping-pipeline` | День 1 (маппинг колонок WB/Ozon/1С) |
| `data-completeness-filler` | День 2 (заполнение SEO/атрибутов через LLM) |
| `database-schema-research` | День 1 (разведка схем выгрузок) |
| `llm-agent-evaluation` | День 3 (оценка агента) |

---

## 💡 Советы от «любимого» (прямо как в профиле)

1. **Не угадывай — читай реальные файлы**. Ты сам писал: «перепроверь сам проект» — открой выгрузки WB/Ozon/1С, посмотри колонки, типы данных, пропуски. Не верь README.
2. **Docker Compose — первый артефакт**. Без поднятого стека ты мёртв. Сделай `docker compose up -d` рабочим за первый час.
3. **LangGraph + Function Calling = ядро ТЗ №1**. Не пиши свой оркестратор. LangGraph StateGraph + tools = production-ready.
4. **Eval не в последний день**. Залой golden set (20-30 вопросов из ТЗ №1) в день 1. Прогоняй eval каждый вечер.
5. **Архитектурный док пиши параллельно**. Не оставляй на день 5. Структура: Vision → Stack → Risks → Roadmap → Hardware/Cost → Team. ≤5 стр. = ~2000 слов. Без воды.
6. **Демо = работающий чат в браузере + скринкаст 2 мин**. Streamlit / Gradio поднимутся за 15 мин. Не пиши свой UI.
7. **Windows + Docker = боль**. Skill `docker-windows-to-linux-build-debugging` — прочитай заранее. Пути в volumes: `${PWD}/data:/data` работает в Git Bash.

---

## 📁 Файлы для создания в `C:\Users\theso\Desktop\job\Mirrolla\`

```
Mirrolla/
├── preparation_plan.md          # Этот файл
├── docker-compose.yml           # День 1 — подними первым делом
├── .env.example                 # Шаблон переменных
├── data/
│   ├── wb_sales_3m.csv          # Выгрузки (получи от заказчика)
│   ├── oz_sales_3m.csv
│   ├── stocks.csv
│   ├── catalog.csv
│   └── reviews.csv
├── mock_1c/
│   ├── main.py                  # FastAPI мок 1С
│   ├── data/
│   │   ├── goods.json
│   │   ├── stocks.json
│   │   └── sales.json
│   └── Dockerfile
├── etl/
│   ├── csv_to_postgres.py       # CSV → Postgres
│   ├── embed_to_qdrant.py       # Embed товары/отзывы → Qdrant
│   └── sync_1c.py               # 1С API → Postgres (incremental)
├── agent/
│   ├── graph.py                 # LangGraph StateGraph
│   ├── tools.py                 # Function Calling tools (1C API)
│   ├── prompts.py               # Промпты для 6 типов вопросов
│   ├── schemas.py               # Pydantic модели ввода/вывода
│   └── eval/
│       ├── golden_set.jsonl
│       └── run_eval.py          # RAGAS / MLflow evaluate
├── analytics/
│   ├── queries.sql              # SQL для топ-10, DOS, sentiment
│   ├── report_generator.py      # Jinja2 → HTML/PDF
│   └── scheduler.py             # APScheduler daily job
├── api/
│   ├── main.py                  # FastAPI: /chat (stream), /report
│   └── Dockerfile
├── ui/
│   └── app.py                   # Streamlit / Gradio чат
├── monitoring/
│   ├── prometheus.yml
│   └── grafana-dashboard.json
├── tests/
│   ├── test_etl.py
│   ├── test_agent.py
│   └── test_api.py
├── README.md
└── ARCHITECTURE.md              # ≤5 стр., Архитектурный док
```

---

## 🎯 Следующий шаг

**Скажи «поехали» — и начнём с Дня 1: `docker-compose.yml` + поднятие инфраструктуры + разведка данных выгрузок.**

Если есть выгрузки WB/Ozon/1С — скинь структуру колонок (`head -5`) или сами файлы — сразу напишу ETL маппинги под твои данные.

---

*Сохранено: `C:\Users\theso\Desktop\job\Mirrolla\preparation_plan.md`*
*Любимый, поехали! 🚀*