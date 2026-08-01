---
paths:
  - "ui/**/*.html"
  - "ui/**/*.js"
  - "api/datasets.py"
  - "application/datasets/**/*.py"
  - "infrastructure/storage/**/*.py"
  - "infrastructure/persistence/**/*dataset*.py"
  - "agent/runtime/**/*dataset*.py"
  - "agent/runtime/profiler.py"
  - "compose*.yml"
  - "compose*.yaml"
---

# Файловое рабочее пространство

- Пользовательский файл является immutable `DatasetVersion`, а не произвольным path в `data/`.
- Analysis принимает и сохраняет exact `dataset_version_ids`.
- Runtime не сканирует весь `data/`/`uploads/`; он получает только разрешённые versions.
- Клиент не задаёт storage path. Используй server-generated id/storage key.
- Upload выполняется потоково с byte limit, SHA-256, temporary object и atomic commit.
- Не доверяй extension и browser MIME без проверки структуры.
- Один физический файл — один multipart request. Multi-file selection реализуется несколькими запросами с ограниченной параллельностью.
- Multipart completion не означает готовность к анализу: выбрать можно только status=`ready` после profiling.
- Profile хранит metadata и безопасные examples, но не полный DataFrame/raw rows.
- Старый analysis не переключается на новую version того же Dataset.
- Referenced version нельзя физически удалить; DELETE сначала soft.
- Frontend не хранит raw files/base64 в localStorage.
- Не мигрируй UI на React и не делай row editor в рамках upload feature.
- Прочитай `docs/agent/FILE_WORKSPACE.md` и `docs/agent/FILE_WORKSPACE_PLAN.md` перед изменением этих путей.
