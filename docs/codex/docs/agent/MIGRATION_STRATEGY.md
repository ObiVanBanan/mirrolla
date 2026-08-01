# Стратегия миграции

Это порядок архитектурного развития, а не разрешение менять всё одним PR.

## Принцип

Сначала создаётся один полностью работающий vertical slice. Только после review и доказательств паттерн тиражируется.

## 1. Characterization baseline

До рефакторинга зафиксировать тестами:

- contracts Router/Planner/ExecutionResult;
- skill loading;
- CI JSON parsing;
- fallback без внешнего API;
- текущие approve/revise/reject transitions.

Цель — отличать намеренное изменение от случайной регрессии.

## 2. Добавить файловое рабочее пространство

До нового runtime создать безопасный путь данных:

- DataWorkspace, Dataset и immutable DatasetVersion contracts;
- RawFileStorage boundary и local persistent adapter;
- потоковый multipart upload;
- profile status `profiling/ready/invalid`;
- frontend panel загрузки и выбора;
- `dataset_version_ids` в create analysis;
- soft delete и запрет удаления referenced versions.

Выполнять по `docs/agent/FILE_WORKSPACE_PLAN.md`. Старый question-only request временно сохраняется для совместимости.

## 3. Выделить exemplar runtime contracts

Только для `sales-decline-analysis` добавить:

- versioned skill metadata;
- selected dataset versions, registry/profile;
- semantic mapping;
- execution manifest;
- generated result schema;
- generic и sales-specific validators.

Старый path остаётся за feature flag, пока exemplar не проверен.

## 4. Разделить Executor

Из монолита выделить чистые компоненты:

```text
SkillLoader
DatasetResolver
Profiler
SemanticMapper
ManifestBuilder
ReferenceLoader
PromptBuilder
CIExecutionService
ResultParser
ValidationService
RepairController
```

`execute_plan()` временно может быть facade, но не должен продолжать содержать реализацию каждого слоя.

## 5. Доказать schema flexibility

Exemplar обязан пройти fixtures, где:

- переименован product identifier;
- переименована date column;
- один источник разбит на несколько файлов;
- optional stocks/reviews отсутствуют;
- required date отсутствует;
- previous period равен нулю;
- модель использовала несуществующую колонку;
- результат содержит неверную формулу и repair её исправляет.

## 6. Унифицировать orchestration

После стабилизации runtime:

- создать application service;
- сделать LangGraph единственной state machine;
- перевести API и CLI на один service;
- спрятать persistence за repository abstraction.

Не смешивать этот шаг с разработкой profiler/validator в одном большом изменении.

## 7. Надёжное выполнение

Затем вынести long-running execution из FastAPI process в worker, добавить idempotency, attempts и recovery.

## 8. Тиражировать pattern

Переносить по одному:

1. inventory planning;
2. portfolio growth;
3. reviews and pricing.

Для каждого — собственные concepts, output rules и validator. Не создавать giant validator с ветвлением по всем skills.

## 9. Persistence и data versions

После стабилизации контрактов можно переносить metadata/checkpoints в PostgreSQL и хранить immutable dataset versions. Схема БД должна следовать уже доказанным runtime contracts, а не опережать их.

## Что считается завершённым exemplar

- файлы можно загрузить и выбрать через frontend;
- analysis закрепляет exact DatasetVersion ids;
- физические изменения колонок не требуют правки pipeline code;
- generated code сохранён;
- manifest сохранён;
- output проходит deterministic validation;
- missing data обрабатывается честно;
- bounded repair протестирован;
- старый path не сломан;
- reviewer подтвердил интеграцию, а не только unit tests.
