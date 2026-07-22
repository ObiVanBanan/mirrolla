# Mirrolla AI — Аналитический ассистент маркетплейсов

AI-ассистент для менеджеров WB+Ozon, отвечающий на вопросы о продажах, остатках, отзывах и росте товаров на основе данных 1С и маркетплейсов.

## Что умеет

- **Почему упали продажи?** — диагностика конкретного SKU
- **Какие товары заканчиваются?** — топ критических остатков с приоритетами
- **Что заказать в производство?** — рекомендации по объёмам
- **Что растёт быстрее рынка?** — лидеры относительно категории
- **Какие отзывы требуют реакции?** — приоритетная очередь для менеджера

## Архитектура

```
Вопрос менеджера
  ↓
Router (gpt-4o-mini) → skill + коды + период
  ↓
Planner (gpt-4o) → структурированный план (гипотезы, датасеты, метод)
  ↓
[HITL interrupt — approve / revise / reject]
  ↓
Executor (OpenAI Code Interpreter) → фактура (findings)
  ↓
Reporter (gpt-4o) → человекочитаемый ответ менеджеру
```

**Стек:** Python 3.12, FastAPI, LangGraph, OpenAI Responses API (Code Interpreter), SQLite checkpointer.

## Быстрый старт (Docker)

```bash
# 1. Скопировать и заполнить .env
cp .env.example .env
# Вписать OPENAI_API_KEY

# 2. Запустить
docker compose up --build

# 3. Открыть
# UI:   http://localhost:8080    ← чат-интерфейс (nginx отдаёт HTML)
# API:  http://localhost:8000/docs ← FastAPI Swagger
```

## Быстрый старт (без Docker, локально)

**Требования:** Python 3.12+, доступ к OpenAI API.

```bash
# 1. Виртуальное окружение
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Зависимости
pip install -r requirements.txt

# 3. Конфиг
cp .env.example .env
# Вписать OPENAI_API_KEY (= переменная token)

# 4. Данные
# Положить xlsx-файлы в data/:
#   data/озон 17.03-16.04.xlsx
#   data/озон 17.04-16.05.xlsx
#   data/озон 17.05-16.06.xlsx
#   data/Отзывы ВБ 17.03-17.06.2026.xlsx
# Выгрузить products.json из 1С (через client/onec_client.py)

# 5. Запуск
uvicorn api.main:app --port 8000    # API на :8000

# 6. Открыть UI
# Файл: ui/mirrolla_assistant.html (в браузере)
# или запустить nginx: cd ui && python -m http.server 8080
```

## Использование

### UI (рекомендуется)

Открыть `ui/mirrolla_assistant.html` в браузере → задать вопрос → подтвердить план → получить ответ.

### API

```bash
# Создать анализ
curl -X POST http://localhost:8000/api/v1/analyses \
  -H "Content-Type: application/json" \
  -d '{"question":"какие товары заканчиваются?"}'

# → {"id": "uuid", "status": "awaiting_approval", "plan": {...}}

# Подтвердить
curl -X POST http://localhost:8000/api/v1/analyses/{id}/approve

# → {"status": "executing", ...}

# Получить результат (poll)
curl http://localhost:8000/api/v1/analyses/{id}

# → {"status": "done", "result": {"findings": [...], "summary": "..."}}
```

### CLI (LangGraph, с HITL)

```bash
# Новый анализ
python -m agent "какие товары заканчиваются?"

# План появится, сервис остановится на interrupt.
# Thread ID: xxx → сохранить.

# Через час (или день) — resume:
python -m agent --resume xxx approve
python -m agent --resume xxx revise "период 30 дней"
python -m agent --resume xxx reject

# Список всех анализов
python -m agent --list
```

### Авто-отчёт (фиксированный workflow)

```bash
# 1. Запустить API
uvicorn api.main:app --port 8000 &

# 2. Запустить генерацию отчёта
python -m reports.generator --output reports/output/management_report.md
```

Сгенерирует 4 анализа (топ-10 рост, топ-10 падение, критические остатки, негатив отзывы) и соберёт markdown-отчёт.

## Структура проекта

```
mirrolla/
├── agent/
│   ├── router.py         # классификация вопроса
│   ├── planner.py        # план анализа
│   ├── executor.py       # запуск через OpenAI Code Interpreter
│   ├── ci_runner.py      # Responses API + Code Interpreter
│   ├── reporter.py       # LLM-синтез ответа
│   ├── graph.py          # LangGraph StateGraph + interrupt
│   ├── nodes.py          # узлы графа
│   └── schemas.py        # Pydantic модели (Finding, ExecutionResult)
├── api/
│   └── main.py           # FastAPI (7 эндпоинтов)
├── ui/
│   ├── mirrolla_assistant.html  # чат-интерфейс (порт 8080 в Docker)
│   └── nginx.conf        # конфиг для Docker UI
├── reports/
│   └── generator.py      # авто-отчёт
├── data/                 # Ozon/WB xlsx, products.json
├── client/
│   └── onec_client.py    # 1С интеграция
├── helpers/              # чистый Python аналитики
├── tools/                # утилиты: smoke-тест, генерация синтетики, raw CI
├── docs/                 # архитектурный документ, план, презентация
├── Dockerfile
├── compose.yaml
├── requirements.txt
└── README.md
```

## Переменные окружения

| Переменная | Назначение | Дефолт |
|------------|------------|--------|
| `token` | OpenAI API key | (обязательно) |
| `MIRROLLA_API` | URL API для авто-отчёта | `http://127.0.0.1:8000/api/v1` |
| `ROUTER_MODEL` | Модель для router | `gpt-4o-mini` |
| `PLANNER_MODEL` | Модель для planner | `gpt-4o` |
| `EXECUTOR_MODEL` | Модель для CI | `gpt-4o-mini` |
| `REPORTER_MODEL` | Модель для синтеза ответа | `gpt-4o` |
| `ONE_C_URL` | URL 1С (для pre-fetch balances) | (не задан) |
| `ONE_C_USER` | Пользователь 1С | (не задан) |
| `ONE_C_PASS` | Пароль 1С | (не задан) |
| `API_KEY` | API ключ для защиты POST эндпоинтов | (пусто = auth отключена) |
| `CORS_ORIGINS` | CORS origins через запятую | `http://localhost:8080,...` |

## Известные ограничения

- **Цены** — нет данных о ценах продажи, нельзя рассчитать оптимальную цену
- **WB заказы** — WB-выгрузка содержит только отзывы, нет данных о заказах
- **Сравнение с рынком** — нет внешних данных, сравниваем с собственной категорией
- **Остатки 1С** — текущий snapshot, нет истории

## Лицензия

Internal use only.