---
paths:
  - "agent/**/*.py"
  - "api/**/*.py"
  - "client/**/*.py"
  - "helpers/**/*.py"
  - "reports/**/*.py"
  - "worker/**/*.py"
  - "infrastructure/**/*.py"
---

# Архитектурные границы

- Доменный и runtime-код не должен зависеть от FastAPI request/response объектов.
- API является transport adapter: validation, auth, serialization и вызов application service.
- LangGraph/application layer владеет workflow transitions; API и CLI не воспроизводят их вручную.
- Интеграции OpenAI и 1С находятся за явными boundaries, пригодными для mock.
- Pydantic contracts являются публичными границами. При их изменении найди и обнови всех callers.
- Не передавай между слоями DataFrame без необходимости. Сохраняемые состояния должны быть сериализуемыми и компактными.
- Чистые components не читают env-переменные внутри бизнес-метода; configuration передаётся явно или через composition root.
- Новый cross-cutting pattern сначала реализуется на одном exemplar и документируется в `docs/agent/DECISIONS.md`.
- Не создавай абстракцию, если существует только один конкретный use case и нет ясной границы тестирования.

- Пользовательские данные входят через DatasetService/RawFileStorage, а не через прямой доступ API к `data/`.
- Analysis state содержит dataset version ids и компактные metadata, но не raw bytes/DataFrame.
