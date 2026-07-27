# Текущая архитектура

Статус документа: обзор ветки `main`, выполненный 2026-07-27.

Этот файл описывает фактический baseline. Наличие паттерна в текущем коде не означает, что его нужно копировать.

## Заявленный pipeline

```text
Router
→ Planner
→ HITL approve/revise/reject
→ Executor + OpenAI Code Interpreter
→ Reporter
```

## Фактические компоненты

### Router — `agent/router.py`

Выбирает skill, извлекает product codes и период. Имеет LLM и fallback-поведение.

### Planner — `agent/planner.py`

Читает `agent/skills/<skill>/SKILL.md`, строит `AnalysisPlan` и fallback plans. Сейчас prompt и fallback-логика частично знают конкретный snapshot данных.

### CLI orchestration — `agent/graph.py`, `agent/nodes.py`

LangGraph управляет interrupt/resume для approve, revise и reject. Checkpoint хранится отдельно.

### HTTP orchestration — `api/main.py`

FastAPI вручную вызывает Router, Planner и Executor, хранит собственные статусы и данные в отдельной SQLite-базе. После approve использует `BackgroundTasks`.


### UI и текущая доставка данных

`ui/mirrolla_assistant.html` — большой single-file vanilla frontend. Он создаёт analyses и показывает plan/result, но не имеет файлового workspace, upload queue и выбора dataset versions.

Текущие marketplace exports должны заранее лежать в project `data/`. В Docker каталог монтируется в API container. API не имеет CRUD/upload endpoints для datasets, поэтому пользователь не может управлять входными файлами через продуктовый интерфейс.

Это baseline, а не целевая модель. Новый upload flow должен создавать immutable DatasetVersion, а не просто копировать client filename в существующую папку.

#### Текущие callers analysis API

- `createAnalysis()` → `apiCreate(question)` → `POST /api/v1/analyses` с legacy payload только вида `{question}`.
- `loadAnalysis(id)` → `apiGet(id)` → `GET /api/v1/analyses/{id}` для открытия истории и восстановления состояния после reload.
- `approve()` → `apiApprove(id)` → `POST /api/v1/analyses/{id}/approve`.
- `revise()` → `apiRevise(id, feedback)` → `POST /api/v1/analyses/{id}/revise`.
- `reject()` → `apiReject(id)` → `POST /api/v1/analyses/{id}/reject`.

#### Текущие polling и history semantics

- История хранится только в runtime-состоянии frontend (`analyses`, `currentAnalysisId`) и наполняется ответами API.
- `pollForUpdates(id)` опрашивает `GET /api/v1/analyses/{id}` каждые 5 секунд до terminal status: `done`, `error` или `rejected`.
- После reload UI не восстанавливает список analyses из отдельного history endpoint; восстановление происходит только если пользователь повторно откроет конкретный analysis, id которого уже известен приложению в текущей сессии.

#### Mounted data path baseline

- `compose.yaml` монтирует `./data:/app/data` в сервис `api`.
- Текущий runtime читает файлы из этого общего mounted path, а не из пользовательского upload workspace.
- `ui/nginx.conf` проксирует только `/api/` на backend и не добавляет upload-specific routing.

### Executor — `agent/executor.py`

Текущий Executor объединяет слишком много обязанностей:

- получение остатков 1С;
- выбор физических файлов;
- статическое описание schema;
- загрузку skill;
- загрузку полного source helpers;
- prompt construction;
- вызов Code Interpreter;
- JSON parsing;
- validation;
- retry;
- Reporter;
- сбор `ExecutionResult`.

### CIRunner — `agent/ci_runner.py`

Загружает файлы в OpenAI, запускает Responses API с Code Interpreter и использует `previous_response_id` для runtime self-correction. Сгенерированный код виден в событиях, но текущий верхний pipeline не сохраняет его как полноценный artifact.

### Reporter — `agent/reporter.py`

Получает структурированные findings и формирует ответ. Это правильная граница: Reporter инструктирован не выдумывать и не пересчитывать данные.

### Skills — `agent/skills/*/SKILL.md`

Содержат сильную бизнес-методику, hypotheses, formulas, priority rules и ограничения. Одновременно в них находятся mutable snapshot facts: filenames, row counts, physical columns и текущие date ranges.

### Helpers — `helpers/*.py`

Содержат reference analytics. Planner указывает релевантные helper names, но Executor сейчас инжектирует полные исходники всех helper modules.

## Главные архитектурные разрывы

### 1. Две state machines

```text
CLI → LangGraph → checkpoint DB
API → ручные переходы → analyses DB → BackgroundTasks
```

Они могут расходиться по статусам, retry, revise и persistence semantics.

### 2. Static data knowledge

`agent/executor.py` содержит конкретные filenames и большой `DATA_SCHEMA`. `SKILL.md` и Planner также содержат факты текущей выгрузки. Новая структура данных требует изменения кода и prompt-текста в нескольких местах.

### 3. Монолитный Executor

Компонент сложно тестировать изолированно. Любое изменение рискует затронуть acquisition, prompt, execution, parsing, validation и reporting одновременно.

### 4. Слабый audit trail

Недостаточно явно сохраняются:

- точные версии datasets;
- semantic mapping;
- execution manifest;
- полный generated code;
- validation report;
- цепочка repair attempts.

### 5. Validation после факта

Существующая проверка в основном валидирует форму ответа и несколько семантических условий. Она не подтверждает большинство skill-specific formulas и provenance используемых колонок.

### 6. Нет пользовательского data workspace

Файлы не являются ресурсами приложения: нет ids, version lifecycle, profile status, selection per analysis и безопасного upload boundary. Анализ зависит от глобального содержимого `data/`.

### 7. Ненадёжный background execution

FastAPI `BackgroundTasks` работает в процессе API. Рестарт может оборвать анализ, а статус остаться `executing`.

## Что нужно сохранить

- Router → Planner → HITL → Executor → Reporter как понятную продуктовую модель.
- Pydantic structured contracts.
- LangGraph interrupt/resume идею.
- Hosted Code Interpreter как изолированный code-generation runtime.
- Существующую бизнес-методику skills.
- Helpers как reference code.
- Reporter как отдельный слой объяснения.
- Явные limitations при отсутствии данных.

## Что нельзя размножать

- новые списки конкретных filenames в Python;
- новый глобальный static schema prompt;
- ещё одну ручную status machine;
- новый mega-module, объединяющий весь runtime;
- retry с потерей execution context;
- mutable dataset facts внутри вечной business methodology;
- upload endpoint, который сохраняет файл под client filename и затем сканирует всю папку;
- analysis, который использует «последний файл» вместо pinned version id;
- validation, основанную на доверии к пояснительному тексту модели.
