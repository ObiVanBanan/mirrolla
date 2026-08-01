# Файловое рабочее пространство

## Цель

Менеджер должен иметь возможность загрузить один или несколько файлов через текущий web UI, дождаться их проверки и профилирования, выбрать нужные версии и создать анализ именно по ним.

Файл после загрузки не становится «просто путём в `data/`». Он становится версионированным ресурсом приложения с идентификатором, checksum, статусом, profile и связями с анализами.

## Пользовательский поток

```text
Менеджер открывает панель «Данные»
  ↓
выбирает или перетаскивает XLSX/CSV/JSON
  ↓
UI загружает каждый файл отдельным multipart-запросом
  ↓
API потоково сохраняет raw file и считает SHA-256
  ↓
DatasetVersion получает status=profiling
  ↓
Profiler строит безопасный profile
  ├─ успешно → status=ready
  └─ ошибка → status=invalid + понятные issues
  ↓
Менеджер выбирает ready-версии для анализа
  ↓
POST /analyses получает dataset_version_ids
  ↓
Plan и approval показывают выбранные файлы и ограничения
  ↓
Execution Manifest фиксирует точные version ids и checksums
  ↓
Code Interpreter получает только выбранные raw files
```

## Сущности

### DataWorkspace

Контейнер доступных пользователю данных.

На первом этапе без multi-user auth разрешён один default workspace. Наличие default workspace не должно встраиваться в доменную логику навсегда: API и repository всё равно принимают `workspace_id`.

Минимальные поля:

```text
id
name
created_at
```

### Dataset

Логический источник, понятный пользователю: например «Продажи Ozon» или «Отзывы WB».

Минимальные поля:

```text
id
workspace_id
display_name
source_type = upload | connector | system
created_at
```

При первой загрузке без `dataset_id` создаётся новый Dataset. При загрузке с существующим `dataset_id` создаётся новая версия того же логического источника.

### DatasetVersion

Неизменяемый snapshot одного физического файла.

Минимальные поля:

```text
id
dataset_id
original_filename
storage_key
format
size_bytes
checksum_sha256
status
profile_json
issues_json
created_at
deleted_at
```

`storage_key` генерируется сервером. Клиент никогда не задаёт filesystem path.

### AnalysisDatasetSelection

Связь анализа с конкретными версиями данных:

```text
analysis_id
dataset_version_id
position
```

Analysis ссылается не на `Dataset`, не на filename и не на «последнюю версию», а на точные `DatasetVersion.id`.

## Статусы DatasetVersion

```text
receiving   — поток ещё загружается во временный объект
uploaded    — raw file атомарно сохранён и checksum рассчитан
profiling   — выполняется техническое профилирование
ready       — файл можно выбирать для анализа
invalid     — файл сохранён, но формат/profile не прошёл проверку
deleted     — скрыт от новых анализов; физическое удаление отложено
```

Только `ready` можно прикрепить к новому анализу.

## Поддерживаемые форматы первого релиза

```text
.xlsx
.csv
.json
```

Не принимать в первом релизе:

- ZIP/RAR и другие архивы;
- `.xls`;
- macro-enabled Excel;
- PDF и изображения;
- исполняемые файлы;
- URL вместо файла.

Лимит задаётся `MAX_UPLOAD_BYTES`; рекомендуемый dev default — 200 MiB. Значение является конфигурацией, а не константой UI.

## Upload API

### Почему один файл на запрос

Frontend может выбрать много файлов, но загружает каждый отдельным запросом с ограниченной параллельностью. Это даёт независимый progress, retry и результат для каждого файла и не создаёт неясную partial-success семантику одного огромного multipart batch.

### Эндпоинты

```text
GET    /api/v1/workspaces/default
GET    /api/v1/workspaces/{workspace_id}/datasets
POST   /api/v1/workspaces/{workspace_id}/datasets
GET    /api/v1/dataset-versions/{version_id}
GET    /api/v1/dataset-versions/{version_id}/profile
DELETE /api/v1/dataset-versions/{version_id}
```

`POST /datasets` принимает `multipart/form-data`:

```text
file          — обязательный UploadFile
display_name  — optional
dataset_id    — optional; создать новую version существующего Dataset
```

Ответ после сохранения raw file:

```json
{
  "dataset": {
    "id": "...",
    "display_name": "Продажи Ozon"
  },
  "version": {
    "id": "...",
    "original_filename": "ozon_may.xlsx",
    "size_bytes": 123456,
    "checksum_sha256": "...",
    "status": "profiling"
  },
  "deduplicated": false
}
```

Статус profile обновляется через polling существующего GET. SSE можно добавить позже, но он не нужен для первого vertical slice.

## Изменение Analysis API

`CreateAnalysisRequest` расширяется:

```python
class CreateAnalysisRequest(BaseModel):
    question: str
    dataset_version_ids: list[str] = []
```

Правила application service:

1. Проверить существование каждой version.
2. Проверить принадлежность одному workspace.
3. Проверить `status == ready`.
4. Удалить дубликаты id, сохранив порядок.
5. Сохранить selection до Planner/Executor.
6. Передать Planner profiles выбранных versions.
7. Зафиксировать versions и checksums в Execution Manifest.

Во время миграции пустой список может использовать legacy system datasets только при явном feature flag `LEGACY_DATA_DIR_ENABLED=true`. Новый UI всегда отправляет явный список выбранных version ids.

## Storage boundary

Application layer не работает напрямую с `Path`, `shutil` или Docker volume.

Контракт:

```python
class RawFileStorage(Protocol):
    def put_stream(self, version_id: str, stream, max_bytes: int) -> StoredObject: ...
    def open_read(self, storage_key: str): ...
    def delete(self, storage_key: str) -> None: ...
```

Первая реализация — local filesystem adapter:

```text
data/uploads/{workspace_id}/{dataset_id}/{version_id}/raw/{server_generated_name}
```

В БД хранится `storage_key`, а не абсолютный путь.

Docker должен монтировать отдельный persistent volume для uploads. Нельзя полагаться на writable layer контейнера.

Production object storage пока не выбирается; интерфейс должен позволять заменить local adapter без изменения DatasetService.

## Безопасная загрузка

Upload handler обязан:

1. Создать server-generated id и временный `.part` object.
2. Читать поток кусками, не загружая файл целиком в память.
3. Одновременно считать SHA-256 и число байт.
4. Немедленно остановиться при превышении `MAX_UPLOAD_BYTES`.
5. Нормализовать и хранить original filename только как metadata.
6. Проверить extension и фактическую структуру файла.
7. После успеха выполнить atomic rename/commit.
8. При ошибке удалить temporary object и записать typed issue.

Дополнительные правила:

- запретить `../`, абсолютные пути и control characters в отображаемом имени;
- не доверять `Content-Type` браузера;
- для XLSX не исполнять formula/macro content;
- profiler читает workbook в read-only/data-only режиме;
- не логировать содержимое файла;
- raw file не отдаётся публичным static URL;
- API download endpoint не нужен для первого релиза;
- одинаковый checksum внутри workspace не должен хранить второй blob.

## Профилирование

После commit вызывается `DatasetProfileJob(version_id)` через job-dispatch boundary.

HTTP route не должна сама строить полный profile большого файла. Для unit tests разрешён synchronous fake dispatcher. Реальный способ запуска worker выбирается отдельным инфраструктурным решением.

Profiler сохраняет:

- worksheets для XLSX;
- row/sample count;
- columns и inferred types;
- null ratios и unique counts;
- до пяти безопасных examples на колонку;
- date/numeric ranges;
- encoding/delimiter warnings для CSV;
- structure warnings для JSON;
- checksum уже сохранённой raw version.

Profile не содержит полный DataFrame и не превращает исходный файл в новую «истину».

## Frontend contract

Первый релиз изменяет существующий `ui/mirrolla_assistant.html`; переход на React или другой framework запрещён в этой задаче.

### Панель «Данные»

Добавить:

- кнопку в header или sidebar;
- drawer/modal с drag-and-drop зоной;
- `<input type="file" multiple accept=".xlsx,.csv,.json">`;
- очередь загрузок;
- список загруженных DatasetVersion;
- status, filename, size, format, created time;
- краткий profile: sheets, columns, date range, warnings;
- checkbox выбора ready versions;
- действие «удалить» только для неиспользуемых/soft-deletable versions.

### Progress

Для upload progress использовать `XMLHttpRequest`, потому что обычный `fetch` не даёт надёжного progress события загрузки во всех браузерах. Остальные API-вызовы продолжают использовать текущий fetch helper.

Frontend загружает не более трёх файлов одновременно.

### Composer

Над полем вопроса показывать chips выбранных данных:

```text
[ozon_may.xlsx ×] [wb_reviews.xlsx ×]
```

Удаление chip снимает выбор, но не удаляет dataset version.

Кнопка отправки формирует:

```json
{
  "question": "Почему упали продажи?",
  "dataset_version_ids": ["...", "..."]
}
```

Не хранить raw files или base64 в localStorage. Допустимо хранить только ids последнего workspace и выбранных versions для удобства, но backend остаётся источником истины.

### Состояния UI

- `uploading` — progress bar и cancel текущего XHR;
- `profiling` — spinner, version нельзя выбрать;
- `ready` — version можно выбрать;
- `invalid` — показать понятные issues и позволить удалить/перезагрузить;
- `deleted` — не показывать в обычном списке.

UI не должен считать файл готовым только потому, что multipart request завершился.

## Работа с выбранными файлами

Planner и Executor запрещено сканировать весь `data/` или `uploads/`.

На вход runtime получает уже разрешённый набор:

```python
ResolvedDatasetVersion(
    id=...,
    dataset_id=...,
    original_filename=...,
    storage_key=...,
    checksum_sha256=...,
    profile=...,
)
```

Далее:

- Semantic Mapper видит только profiles выбранных versions;
- Plan перечисляет, какие версии будут использованы;
- approve фиксирует selection;
- Code Interpreter загружает только выбранные raw files;
- Result validator запрещает ссылаться на другие dataset ids/columns;
- history analysis показывает использованные filenames и checksums.

## Иммутабельность и удаление

После создания analysis его selection неизменяемо. Revise меняет план, но не должен молча переключаться на «последнюю» версию Dataset.

Если пользователь хочет другие файлы, создаётся новая plan version с явным изменением selection или новый analysis.

DatasetVersion, на которую ссылается analysis, нельзя физически удалить. DELETE делает soft delete и скрывает её для новых анализов. Garbage collection разрешён только для unreferenced versions после retention period.

## Deduplication

Если в одном workspace уже существует version с тем же SHA-256:

- второй blob не создаётся;
- API возвращает существующую version или новую metadata-ссылку на тот же storage object;
- поведение должно быть детерминированным и покрыто тестом;
- filename не используется как признак идентичности.

Для первого релиза рекомендуется вернуть существующую version и `deduplicated=true`.

## Наблюдаемость

Структурированные события:

```text
dataset_upload_started
dataset_upload_completed
dataset_upload_rejected
dataset_profile_started
dataset_profile_completed
dataset_profile_failed
dataset_attached_to_analysis
```

Логировать ids, format, size, duration и issue codes. Не логировать raw content, samples и полный profile.

## Не делать в первом vertical slice

- multipart resumable uploads;
- direct-to-S3 signed uploads;
- совместное редактирование workspace;
- row-level spreadsheet editor;
- ручное переименование колонок в UI;
- полноценную таблицу preview всего файла;
- автоматическое объединение файлов до Planner;
- RAG или embedding загруженных таблиц;
- скачивание raw file через публичный endpoint;
- auth/tenancy redesign;
- React migration.
