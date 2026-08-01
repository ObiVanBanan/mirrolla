---
name: implement-file-workspace
description: Выполнить одну фазу плана загрузки и использования пользовательских файлов в Mirrolla.
---

# Implement File Workspace

Используй только когда задача относится к upload, dataset workspace, profiling, выбору файлов или привязке данных к analysis.

## Сначала прочитай

1. `CLAUDE.md`.
2. `docs/agent/FILE_WORKSPACE.md`.
3. `docs/agent/FILE_WORKSPACE_PLAN.md`.
4. `docs/agent/DECISIONS.md`.
5. Релевантные `.claude/rules/`.

## Протокол

1. Определи номер одной фазы F0–F9.
2. Не выполняй соседние фазы.
3. Перечисли точные файлы в scope.
4. Найди существующие callers и tests.
5. Реализуй только acceptance criteria выбранной фазы.
6. Запусти targeted tests, compileall и при Compose-изменениях `docker compose config`.
7. Остановись после отчёта.

## Запрещено

- создавать upload route, который пишет прямо в произвольный filename;
- читать весь upload в bytes до сохранения;
- делать profile большого файла внутри FastAPI route;
- отправлять filenames вместо version ids в analysis contract;
- сканировать global `data/` для нового user analysis;
- изменять старые analysis selections после re-upload;
- переходить на React;
- добавлять S3, auth redesign или resumable uploads без отдельного решения.

## Формат результата

```text
OUTCOME
PHASE
FILES CHANGED
VERIFICATION
ACCEPTANCE CRITERIA
OPEN ITEMS
```
