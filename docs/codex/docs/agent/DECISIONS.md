# Зафиксированные архитектурные решения

Агент не должен переоткрывать эти решения внутри обычной implementation-задачи.

## D-001 — Model-generated code is core

**Статус:** accepted.

Модель самостоятельно пишет Python-код под текущие данные. Фиксированный Tool Registry не является основным execution engine.

**Следствие:** качество контролируется не идентичностью кода, а manifest, runtime restrictions и validators.

## D-002 — Skills describe methodology

**Статус:** accepted.

Skill — доменная методика, reference examples и output/validation contract. Skill не равен функции и не равен prompt с текущей схемой выгрузки.

## D-003 — Physical schemas are discovered

**Статус:** accepted.

Файлы, листы, колонки и date ranges профилируются во время выполнения. Business concepts связываются с ними через semantic mapping.

## D-004 — Helpers remain references

**Статус:** accepted.

`helpers/` сохраняются как проверенные примеры, тестовые oracle-функции и возможные reusable utilities. Они не должны незаметно заменить code generation.

## D-005 — Validation is deterministic

**Статус:** accepted.

Schema, provenance, formulas и skill invariants проверяются обычным кодом. LLM не решает, корректен ли собственный результат.

## D-006 — Reporter cannot calculate

**Статус:** accepted.

Reporter объясняет validated payload. Изменение чисел, повторный анализ и создание новых findings запрещены.

## D-007 — One workflow

**Статус:** accepted.

API и CLI используют один orchestration/application layer и общую status model. Transport-specific persistence logic не дублирует graph transitions.

## D-008 — Exemplar first

**Статус:** accepted.

Новая архитектура сначала доводится end-to-end на `sales-decline-analysis`. Остальные skills мигрируют только после доказанного паттерна.

## D-009 — Bounded repair

**Статус:** accepted.

После первоначальной попытки допускается максимум две repair-попытки с конкретными validation issues. Третья попытка не запускается автоматически.

## D-010 — Honest insufficiency

**Статус:** accepted.

Отсутствующие required concepts дают `not_enough_data` или непроверяемую hypothesis. Optional data дают limitations/partial analysis.


## D-011 — User files are first-class datasets

**Статус:** accepted.

Файлы загружаются через frontend/API и регистрируются как ресурсы приложения. Копирование файла в глобальную папку не является контрактом продукта.

## D-012 — Dataset versions are immutable and pinned

**Статус:** accepted.

Каждая загрузка создаёт immutable `DatasetVersion` с checksum. Analysis ссылается на точные version ids и не использует filename или «последнюю версию» как identity.

## D-013 — One physical file per upload request

**Статус:** accepted.

Frontend может выбрать много файлов, но отправляет отдельный multipart request для каждого с ограниченной параллельностью. Это обеспечивает независимые progress, retry и status.

## D-014 — Local storage first, storage interface always

**Статус:** accepted.

Первый adapter хранит raw files на persistent local volume. Application layer зависит от `RawFileStorage`, поэтому production object storage можно выбрать позже без изменения DatasetService.

## D-015 — Profiling gates analysis

**Статус:** accepted.

Завершение upload не делает файл готовым. Только DatasetVersion со status=`ready` после профилирования может быть прикреплена к новому analysis.

## D-016 — Explicit data selection

**Статус:** accepted.

Новый user analysis получает `dataset_version_ids`. Runtime не сканирует глобальный `data/`/`uploads/` и не получает доступ к невыбранным файлам.

## Решения, которые пока не приняты

Следующие вопросы нельзя решать попутно:

- точная очередь задач и библиотека worker;
- окончательный production backend для raw files (S3/MinIO/другой);
- использовать ли DuckDB/Parquet как локальный execution cache;
- точная модель semantic mapper;
- окончательная структура Python packages;
- multi-user auth и tenancy;
- public product name и лицензия.

При столкновении с ними остановись, сформулируй варианты и дай рекомендацию. Не внедряй один вариант молча.
