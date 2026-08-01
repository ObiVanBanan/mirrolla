# Целевая архитектура

## Архитектурная формула

```text
LLM планирует и пишет код.
Runtime описывает данные и ограничивает среду.
Validators доказывают допустимость результата.
Reporter объясняет уже проверенную фактуру.
```

## Целевой pipeline

```text
Frontend Data Workspace
  ↓
Upload API → RawFileStorage → DatasetVersion
  ↓
Profile Job → ready/invalid
  ↓
User selects dataset_version_ids
  ↓
User question
  ↓
Router
  ↓
Skill Selector / Skill Package
  ↓
Dataset Registry → Dataset Profiler
  ↓
Semantic Mapper
  ↓
Planner → Human approval
  ↓
Execution Manifest
  ↓
Prompt Builder + relevant reference code
  ↓
Code Interpreter
  ↓
Parser → Generic Validator → Skill Validator
  ├─ valid → Reporter
  └─ invalid → bounded repair in same execution context
```

## Компоненты

### Skill Package

Содержит:

- id и version;
- назначение и trigger examples;
- required/optional business concepts;
- business methodology;
- formulas и priority rules;
- known limitations;
- relevant reference helpers;
- output contract version;
- validator id.

Skill не содержит обязательный physical schema текущего файла.

### File Workspace

Пользователь загружает XLSX/CSV/JSON через frontend. Каждый raw file становится immutable `DatasetVersion` с server-generated storage key, checksum, status и profile. Analysis хранит точные version ids.

Подробный контракт: `docs/agent/FILE_WORKSPACE.md`.

### RawFileStorage

Изолирует application layer от local filesystem или будущего object storage. Upload выполняется chunked, с byte limit, checksum, temporary object и atomic commit. Client filename хранится только как metadata.

### Dataset Registry

Описывает как uploaded, так и system/connector sources через logical ids. Registry не обещает наличие конкретной колонки и не сканирует глобальный каталог для user analysis.

### Dataset Version Lifecycle

```text
receiving → uploaded → profiling → ready
                               └→ invalid
ready/invalid → deleted (soft)
```

Только `ready` version разрешена для нового analysis. Version, связанная с analysis, не удаляется физически.

### Dataset Profiler

Запускается после успешного upload через job boundary и локально получает:

- format, file/sheet identity;
- row count или sample count;
- columns и inferred types;
- null ratio, unique count, safe examples;
- date/numeric ranges;
- checksum и warnings.

Profiler не отправляет raw rows в LLM и не изменяет исходный файл.

### Semantic Mapper

Связывает business concepts с физическими полями:

```text
order_date → ozon_orders / Принят в обработку
product_identifier → ozon_orders / Артикул продавца
sales_amount → ozon_orders / Итого, ₽
```

Сначала используются deterministic aliases, затем structured LLM mapping только по profiles. Низкая confidence для required concept блокирует недостоверный анализ.

### Analysis Plan

Понятный человеку план:

- что проверяем;
- какие периоды и почему;
- какие hypotheses;
- какие данные доступны;
- какие hypotheses непроверяемы;
- какие limitations ожидаются.

План не должен быть Python-кодом.

### Execution Manifest

Неизменяемый контракт одного запуска:

- question;
- skill id/version;
- plan version;
- dataset version ids, original filenames, storage identities и checksums;
- profiles;
- semantic mapping;
- periods;
- filters/groupings;
- assumptions;
- expected output contract;
- runtime restrictions.

Manifest создаётся до code generation и сохраняется.

### Prompt Builder

Собирает фиксированные секции и передаёт только релевантный reference code. Он не вставляет устаревший глобальный schema и не утверждает наличие полей вне profile/mapping.

### Code Interpreter

Модель самостоятельно пишет адаптированный Python-код. Runtime:

- предоставляет только разрешённые datasets;
- не передаёт secrets;
- ограничивает retries;
- сохраняет generated code, logs и artifacts;
- использует тот же execution context для repair, когда возможно.

### Validators

Generic validator проверяет schema, provenance, NaN/inf, dataset/column existence, counts и status semantics.

Skill validator проверяет формулы и бизнес-инварианты конкретного анализа. Validator детерминирован и не вызывает LLM.

### Reporter

Получает только:

- validated findings;
- validated aggregates;
- limitations;
- assumptions;
- ссылки на artifacts.

Reporter не получает право менять числа или выводить новые аналитические findings.

## Где модели разрешена свобода

| Область | Свобода модели |
|---|---|
| Выбор релевантных hypotheses | Да, в рамках skill и доступных данных |
| Адаптация к именам колонок | Да, через подтверждённый mapping |
| Реализация Python-кода | Да |
| Выбор безопасных pandas/DuckDB операций | Да |
| Изменение бизнес-формулы | Нет без явного assumption и нового approval |
| Использование отсутствующих данных | Нет |
| Публикация невалидного результата | Нет |
| Пересчёт Reporter-ом | Нет |

## Оркестрация

Один application/workflow layer используется API и CLI. `CreateAnalysis` получает `dataset_version_ids`, валидирует readiness/ownership и сохраняет selection до Planner. Transport adapters не вызывают Router, Planner и Executor по отдельности и не управляют SQL/status transitions самостоятельно.

Рекомендуемые статусы:

```text
planning
awaiting_approval
queued
executing
completed
partial
not_enough_data
rejected
failed
```

## Надёжность

После стабилизации exemplar execution:

- длительный анализ выносится в worker;
- job становится идемпотентной;
- execution attempts имеют lease/heartbeat;
- metadata и checkpoints переносятся за repository abstraction;
- каждый result ссылается на immutable dataset versions.

Это следующий слой, а не причина откладывать правильный runtime contract.


## Frontend data workspace

Текущий vanilla UI получает панель «Данные»: multi-select, drag-and-drop, отдельный progress каждого файла, statuses profiling/ready/invalid, profile summary и selected-data chips в composer. Первый vertical slice не включает React migration, spreadsheet editor или full row preview.

## Reproducibility rule

Новая upload version никогда не меняет уже созданный analysis. Revise не переключает data selection молча. Execution Manifest и history всегда показывают точные version ids/checksums.
