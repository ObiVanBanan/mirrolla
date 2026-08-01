---
paths:
  - "api/**/*.py"
  - "agent/graph.py"
  - "agent/nodes.py"
  - "agent/__main__.py"
  - "agent/application/**/*.py"
  - "agent/**/*repository*.py"
---

# Workflow и API

- Один analysis имеет один workflow/thread identity.
- Create, approve, revise, reject и resume должны проходить через один application service.
- API endpoint не вызывает Router, Planner и Executor по отдельности.
- API endpoint не пишет workflow SQL напрямую после появления repository abstraction.
- Узлы graph возвращают state updates и не печатают CLI/UI representation.
- Revise создаёт новую plan version; старый approved/rejected plan остаётся доступен для аудита.
- Long-running execution не должен жить в HTTP request lifecycle.
- Job обязана быть идемпотентной: повторная доставка не создаёт второй result.
- Status names и разрешённые transitions определяются в одном месте и проверяются тестами.
- Ошибка внешнего provider не превращается в `completed`.

- Create analysis валидирует и сохраняет exact `dataset_version_ids` до routing/planning.
- API не выбирает файлы через glob, filenames или «последнюю версию».
- Dataset upload/profile lifecycle находится за DatasetService и job dispatcher.
