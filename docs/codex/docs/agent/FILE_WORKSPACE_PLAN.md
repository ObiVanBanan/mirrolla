# План реализации файлового рабочего пространства

Этот план предназначен для слабого implementation-agent. Выполняй одну фазу за проход. После каждой фазы запускай проверки, составляй отчёт и останавливайся.

Перед началом прочитай:

- `CLAUDE.md`;
- `docs/agent/FILE_WORKSPACE.md`;
- `docs/agent/TARGET_ARCHITECTURE.md`;
- `docs/agent/DECISIONS.md`;
- `.claude/rules/file-workspace.md`;
- `.claude/rules/data-security.md`;
- `.claude/rules/workflow-api.md`.

## Общие зафиксированные решения

- Frontend остаётся текущим vanilla HTML/CSS/JS.
- Один физический файл загружается одним multipart request.
- Пользователь может выбрать много файлов; UI отправляет до трёх upload-запросов параллельно.
- Raw files immutable.
- Analysis получает `dataset_version_ids`, а не filenames/paths.
- Новый analysis использует только versions со статусом `ready`.
- Runtime не сканирует глобальную папку данных.
- Upload storage находится за `RawFileStorage`.
- Первая storage-реализация локальная; production object storage не выбирается.
- Профилирование запускается через dispatcher boundary, не внутри API route.
- Старые analyses продолжают ссылаться на прежние versions после новых upload.
- Не переносить UI на React и не объединять эту работу с общей миграцией workflow.

## Рекомендуемые новые пути

Если в репозитории ещё нет эквивалентного application boundary, используй:

```text
application/
├── __init__.py
└── datasets/
    ├── __init__.py
    ├── models.py
    ├── repository.py
    ├── service.py
    └── jobs.py

infrastructure/
├── __init__.py
├── storage/
│   ├── __init__.py
│   └── local_files.py
└── persistence/
    ├── __init__.py
    └── sqlite_datasets.py

api/
└── datasets.py

tests/
├── application/datasets/
├── infrastructure/storage/
└── api/test_datasets.py
```

Не перемещай существующий проект в `src/`.

---

# Фаза F0 — Characterization текущего frontend/API

## Цель

Зафиксировать текущий способ создания analysis и текущую структуру UI до изменений.

## Scope

```text
api/main.py
ui/mirrolla_assistant.html
ui/nginx.conf
compose.yaml
tests/
docs/agent/CURRENT_ARCHITECTURE.md
```

## Действия

1. Найти JS-функцию, которая вызывает `POST /api/v1/analyses`.
2. Найти общий API helper и способ передачи API key.
3. Найти current polling/history state.
4. Добавить API characterization test: старый payload только с `question` всё ещё принимается.
5. Добавить в `CURRENT_ARCHITECTURE.md` раздел о том, что файлы сейчас берутся из mounted `data/`, upload API отсутствует, а UI не управляет datasets.
6. Не менять production behavior.

## Acceptance criteria

- [ ] Все текущие callers создания анализа перечислены.
- [ ] Есть тест старого request contract.
- [ ] Production UI/API поведение не изменено.
- [ ] Документирован текущий mounted-data path.

---

# Фаза F1 — Dataset domain contracts

## Цель

Создать чистые модели и repository/storage protocols без FastAPI и filesystem implementation.

## Создать

```text
application/datasets/models.py
application/datasets/repository.py
application/datasets/service.py
application/datasets/jobs.py
```

## Модели

Минимально:

```python
DatasetVersionStatus = Literal[
    "receiving", "uploaded", "profiling", "ready", "invalid", "deleted"
]

class DataWorkspace(BaseModel): ...
class Dataset(BaseModel): ...
class DatasetVersion(BaseModel): ...
class DatasetProfile(BaseModel): ...
class DatasetIssue(BaseModel): ...
class AnalysisDatasetSelection(BaseModel): ...
```

## Protocols

```python
class DatasetRepository(Protocol): ...
class RawFileStorage(Protocol): ...
class DatasetJobDispatcher(Protocol): ...
```

`DatasetService` не импортирует FastAPI, sqlite3 или concrete filesystem adapter.

## Acceptance criteria

- [ ] Модели сериализуемы Pydantic.
- [ ] Невалидный status отвергается.
- [ ] `storage_key` отделён от `original_filename`.
- [ ] Service тестируется через in-memory fakes.
- [ ] Нет доступа к env внутри доменных методов.

---

# Фаза F2 — Local raw storage

## Цель

Безопасно и потоково сохранять upload на локальный persistent volume.

## Создать

```text
infrastructure/storage/local_files.py
tests/infrastructure/storage/test_local_files.py
```

## Требования

- chunked reading;
- SHA-256 во время записи;
- byte limit;
- `.part` temporary object;
- atomic commit;
- server-generated filename;
- cleanup после исключения;
- path traversal невозможен;
- dedupe по checksum не создаёт второй blob;
- storage возвращает `storage_key`, size и checksum.

## Negative tests

- `../../secret.csv`;
- absolute Windows/Unix path в original filename;
- превышение лимита;
- исключение во время stream;
- пустой файл;
- повторный тот же content;
- неподдерживаемое extension.

## Acceptance criteria

- [ ] Файл не читается целиком в memory.
- [ ] Partial object не остаётся после error.
- [ ] Исходное имя не становится частью trusted path.
- [ ] Повторный content не дублирует blob.

---

# Фаза F3 — SQLite dataset repository и default workspace

## Цель

Сохранять metadata отдельно от raw storage.

## Создать

```text
infrastructure/persistence/sqlite_datasets.py
tests/infrastructure/persistence/test_sqlite_datasets.py
```

## Таблицы

```text
workspaces
datasets
dataset_versions
analysis_datasets
```

Точные поля следуют `FILE_WORKSPACE.md`.

## Правила

- repository владеет SQL;
- API не пишет эти таблицы напрямую;
- default workspace создаётся идемпотентно;
- checksum и storage key сохраняются;
- soft delete не ломает старые analysis links;
- status transitions валидируются service-слоем.

## Acceptance criteria

- [ ] Restart repository сохраняет записи.
- [ ] Повторное создание default workspace возвращает тот же id.
- [ ] Referenced version нельзя hard-delete.
- [ ] List по умолчанию не возвращает deleted.

---

# Фаза F4 — Upload API

## Цель

Добавить изолированный FastAPI router для загрузки и просмотра dataset versions.

## Изменить/создать

```text
api/datasets.py
api/main.py
compose.yaml
ui/nginx.conf
tests/api/test_datasets.py
```

## Endpoints

Реализовать endpoints из `FILE_WORKSPACE.md`.

`POST /datasets`:

1. проверяет auth/rate policy;
2. создаёт receiving metadata;
3. передаёт stream DatasetService;
4. storage считает size/checksum;
5. version становится uploaded/profiling;
6. dispatcher получает profile job;
7. route возвращает metadata, не profile результата.

## Infrastructure

- добавить persistent mount `./data/uploads:/app/data/uploads` или named volume;
- в nginx добавить `client_max_body_size`, согласованный с `MAX_UPLOAD_BYTES`;
- не увеличивать API timeout как замену правильному background profiling.

## Acceptance criteria

- [ ] Multipart upload работает через TestClient.
- [ ] Unsupported type возвращает 415/typed issue.
- [ ] Oversize возвращает 413.
- [ ] API не принимает client filesystem path.
- [ ] Existing analysis endpoints не сломаны.
- [ ] `docker compose config` проходит.

---

# Фаза F5 — Profiler job

## Цель

После upload переводить version в `ready` или `invalid`.

## Изменить/создать

```text
application/datasets/jobs.py
agent/runtime/profiler.py
infrastructure/... dispatcher adapter
tests/application/datasets/test_profile_job.py
tests/runtime/test_profiler.py
```

## Fixtures

- XLSX с несколькими sheets;
- CSV UTF-8 BOM;
- CSV cp1251 или неподдерживаемая encoding с warning;
- JSON list of objects;
- mixed types;
- empty sheet;
- damaged XLSX;
- file исчез из storage.

## Acceptance criteria

- [ ] Success: profiling → ready.
- [ ] Failure: profiling → invalid с issue code.
- [ ] Route не профилирует файл напрямую.
- [ ] Profile не содержит полные строки.
- [ ] Job идемпотентна для ready version.

---

# Фаза F6 — Frontend data workspace

## Цель

Позволить менеджеру загрузить, увидеть и выбрать файлы в текущем UI.

## Scope

```text
ui/mirrolla_assistant.html
```

Не переносить UI на framework и не проводить общий визуальный redesign.

## Реализовать

1. Панель/модальное окно «Данные».
2. Dropzone и hidden multiple file input.
3. Upload queue, до трёх активных XHR.
4. Progress и cancel.
5. Poll status до `ready|invalid`.
6. Список versions и profile summary.
7. Checkbox только для ready.
8. Selected-data chips в composer.
9. Ошибки 413/415/profile issues понятным русским текстом.
10. Не хранить raw/base64 в localStorage.

## Acceptance criteria

- [ ] Можно выбрать несколько файлов.
- [ ] Каждый файл имеет независимый progress/status.
- [ ] Profiling version нельзя выбрать.
- [ ] Invalid version показывает причину.
- [ ] После reload список восстанавливается из API.
- [ ] Удаление chip не удаляет файл.
- [ ] Мобильная раскладка остаётся usable.

---

# Фаза F7 — Attach datasets to analysis

## Цель

Создавать analysis с явным набором dataset versions.

## Изменить

```text
api/main.py или application analysis service
agent/schemas.py
ui/mirrolla_assistant.html
repository migrations/tests
```

## Поведение

- request принимает `dataset_version_ids`;
- backend проверяет ready/workspace;
- selection сохраняется до Planner;
- response/GET analysis возвращает attached dataset summaries;
- UI показывает их в plan/analysis history;
- старый payload без ids работает только по зафиксированному legacy rule.

## Acceptance criteria

- [ ] Unknown version → 404/typed error.
- [ ] Profiling/invalid version → 409.
- [ ] Duplicate ids удаляются без изменения порядка.
- [ ] Analysis history показывает точные версии.
- [ ] Новая загрузка не меняет selection старого analysis.

---

# Фаза F8 — Runtime integration

## Цель

Передать выбранные файлы в profiling/mapping/manifest/code generation pipeline.

## Поведение

- DatasetResolver принимает version ids;
- никаких glob по `data/` для user analysis;
- Semantic Mapper видит только выбранные profiles;
- Manifest содержит version ids/checksums/storage identity;
- CIRunner загружает только выбранные raw files;
- validator запрещает неизвестные datasets/columns;
- generated artifacts ссылаются на manifest.

Первый exemplar — только `sales-decline-analysis`.

## Acceptance criteria

- [ ] Два разных набора файлов дают два разных manifest.
- [ ] CI upload list точно совпадает с selection.
- [ ] Не выбранный файл недоступен prompt/runtime.
- [ ] Re-upload нового файла не меняет старый manifest.
- [ ] Missing concept возвращает limitation/not_enough_data.

---

# Фаза F9 — Delete, retention и audit

## Цель

Закрыть жизненный цикл без потери воспроизводимости.

## Реализовать

- soft delete;
- запрет hard delete referenced version;
- cleanup stale `.part` objects;
- retention для unreferenced deleted versions;
- structured audit events;
- UI подтверждение удаления;
- тесты повторного upload после delete.

## Acceptance criteria

- [ ] Старый analysis воспроизводим после soft delete.
- [ ] Deleted version нельзя выбрать для нового analysis.
- [ ] Cleanup не удаляет referenced raw object.
- [ ] Logs не содержат raw content.

---

# Финальный Definition of Done

- [ ] Файлы загружаются через существующий frontend.
- [ ] Поддерживаются XLSX/CSV/JSON.
- [ ] Upload потоковый и ограниченный по размеру.
- [ ] Каждый файл имеет immutable DatasetVersion и checksum.
- [ ] Profiler переводит version в ready/invalid.
- [ ] Пользователь выбирает ready versions для анализа.
- [ ] Analysis сохраняет exact version ids.
- [ ] Planner/Executor работают только с выбранными файлами.
- [ ] Manifest содержит ids/checksums/profiles.
- [ ] Старые analyses не переключаются на новые uploads.
- [ ] Raw data не попадает в git, browser storage или production logs.
- [ ] Unit/API tests не требуют OpenAI и 1С.
