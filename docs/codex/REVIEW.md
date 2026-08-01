# Mirrolla review policy

Проверяй изменение против продуктового смысла, целевой архитектуры и реальных callers. Не ограничивайся стилем diff.

## Считать Important

Сообщай как важную проблему, если изменение:

- заменяет управляемую генерацию кода обязательным набором фиксированных analytical tools;
- добавляет жёсткую зависимость от конкретного filename, Excel sheet, column name, row count или snapshot date;
- позволяет модели ссылаться на колонку или датасет, которых нет в profile/manifest;
- публикует результат Code Interpreter без schema и business validation;
- позволяет Reporter пересчитывать значения, создавать findings или добавлять факты;
- создаёт второй workflow/status model вместо использования общего orchestration layer;
- выполняет долгий Code Interpreter job внутри HTTP request или теряет job при рестарте;
- делает retry в новом контексте с повторной загрузкой данных без обоснования;
- скрывает validation failures либо заменяет их убедительным текстом;
- нарушает связь результата с version skill, manifest и dataset checksums;
- сохраняет upload под client-controlled path/filename или читает большой файл целиком в память;
- считает файл готовым до profile status=`ready`;
- создаёт analysis по filename, glob или «последней версии» вместо exact dataset version ids;
- позволяет удалить raw version, на которую ссылается существующий analysis;
- передаёт Code Interpreter файлы, не выбранные пользователем;
- коммитит raw бизнес-данные, secrets, внутренние credentials/URL или персональные отзывы;
- меняет публичный Pydantic/API contract без проверки всех callers и migration path.

## Обязательные проверки по зонам

### Skills и prompts

- Вечная бизнес-методика отделена от фактов конкретной выгрузки.
- Reference code представлен как пример для адаптации, а не как неоспоримый физический schema contract.
- Missing data приводит к limitation, а не к выдумке.

### Generated analysis

- Manifest фиксирует skill, datasets, mappings, periods, assumptions и ожидаемый output.
- Validator не зависит от LLM.
- Repair ограничен и получает конкретные machine-readable ошибки.
- Сгенерированный код и validation report сохраняются для аудита.

### File workspace

- Upload потоковый, ограниченный и атомарный.
- DatasetVersion immutable и имеет checksum/status/profile.
- Frontend показывает independent progress и не хранит raw/base64.
- Analysis сохраняет exact selection до Planner.
- New upload не меняет старый analysis.
- DELETE referenced version является soft delete.

### Workflow/API

- CLI и API не расходятся по переходам и статусам.
- Approve/revise/reject действительно продолжают один сохранённый workflow.
- Повторная доставка job идемпотентна.

### Tests

- Внешние OpenAI и 1С вызовы mock-нут в unit-тестах.
- Есть negative case, а не только happy path.
- Для schema flexibility есть fixture с переименованными колонками или изменённой раскладкой файлов.
- Для upload есть tests oversize, unsupported type, path traversal, interrupted stream, dedupe и referenced delete.

## Формат findings

Сначала verdict: `PASS`, `PASS WITH NITS` или `FAIL`.

Каждый finding содержит:

1. severity;
2. `path:line`;
3. нарушенное требование;
4. конкретный сценарий отказа;
5. минимальное доказательство.

На `FAIL` укажи тип:

- `SPECIFICATION` — задача оставила реальное решение исполнителю;
- `CAPABILITY` — задача была точной, но реализация ниже требуемого уровня.

Не исправляй код во время review. Не публикуй больше пяти stylistic nits.
