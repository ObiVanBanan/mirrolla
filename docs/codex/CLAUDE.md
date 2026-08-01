# Mirrolla AI Assistant — постоянный контекст

## Что это за проект

Mirrolla — аналитический AI-ассистент для менеджеров маркетплейсов WB и Ozon. Менеджер может сформулировать вопрос неточно; система должна распознать задачу, предложить понятный план анализа, получить подтверждение, написать и выполнить Python-код по аналитическому skill, проверить результат и объяснить выводы.

Это не обычный чат-бот, не фиксированный BI-дашборд и не набор жёстких аналитических API.

## Главная продуктовая идея

LLM получает свободу адаптировать анализ к фактической структуре данных, но не получает свободу выдумывать данные, менять бизнес-методику молча или публиковать непроверенный результат.

Целевой поток:

```text
frontend file workspace
→ immutable dataset versions
→ question
→ routing
→ skill selection
→ dataset profiling
→ semantic mapping
→ analysis plan
→ human approval
→ execution manifest
→ generated Python code
→ Code Interpreter
→ deterministic validation
→ bounded repair
→ reporter
```

## Непереговорные решения

1. Генерация Python-кода моделью — часть продукта. Не заменяй её обязательным вызовом фиксированных analytical tools.
2. Skill — пакет аналитической методики и reference code, а не исполняемая функция.
3. Фактические файлы, листы, колонки и диапазоны дат определяются из текущих данных. Не закрепляй их как вечную схему.
4. `helpers/` — эталонные реализации, примеры и возможная база валидаторов. Они не обязаны быть единственным execution path.
5. Результат контролируется через manifest, output contract и deterministic validators.
6. Reporter объясняет уже проверенные findings. Reporter не пересчитывает метрики и не добавляет новые факты.
7. При недостатке данных система возвращает limitation, `partial` или `not_enough_data`, а не догадку.
8. API и CLI в целевой архитектуре используют один workflow и одну модель состояния.
9. Сначала полностью реализуется один exemplar: `sales-decline-analysis`. Только после его проверки паттерн переносится на остальные skills.
10. Текущий код — baseline пилота, а не образец для слепого копирования.
11. Пользовательские файлы загружаются через файловое рабочее пространство и получают immutable `DatasetVersion` с checksum/profile.
12. Analysis всегда фиксирует точные `dataset_version_ids`; он не работает с filenames и не переключается молча на новые версии.
13. Новый runtime не сканирует глобальную папку `data/` или `uploads/`, а получает только выбранные пользователем versions.

## Навигация

Перед существенным изменением прочитай только релевантные документы:

- `docs/agent/PROJECT.md` — продукт и пользовательский сценарий.
- `docs/agent/CURRENT_ARCHITECTURE.md` — как система работает сейчас и где долг.
- `docs/agent/TARGET_ARCHITECTURE.md` — целевые компоненты и границы.
- `docs/agent/DECISIONS.md` — уже принятые решения; не переоткрывай их.
- `docs/agent/DOMAIN_GLOSSARY.md` — точные значения терминов.
- `docs/agent/MIGRATION_STRATEGY.md` — безопасный порядок изменений.
- `docs/agent/TASK_BRIEF_TEMPLATE.md` — формат узкой задачи для исполнителя.
- `docs/agent/FILE_WORKSPACE.md` — модель upload, storage, profiling, UI и привязки файлов к analysis.
- `docs/agent/FILE_WORKSPACE_PLAN.md` — пофазный план реализации загрузки через frontend.

Path-scoped правила находятся в `.claude/rules/` и загружаются при работе с соответствующими файлами.

## Текущая карта репозитория

- `agent/router.py` — распознавание intent/skill, кодов товаров и периода.
- `agent/planner.py` — построение плана по `SKILL.md`.
- `agent/executor.py` — текущий монолитный execution pipeline через Code Interpreter.
- `agent/ci_runner.py` — OpenAI Responses API и hosted Code Interpreter.
- `agent/reporter.py` — объяснение структурированных результатов.
- `agent/graph.py`, `agent/nodes.py` — LangGraph и HITL для CLI.
- `agent/skills/` — аналитические skills.
- `helpers/` — reference Python analytics.
- `api/main.py` — текущий FastAPI workflow и SQLite persistence.
- `client/onec_client.py` — интеграция с 1С.
- `reports/` — управленческий отчёт.
- `ui/mirrolla_assistant.html` — текущий vanilla frontend; файловое рабочее пространство добавляется сюда без React-миграции.
- `application/datasets/` и `infrastructure/storage/` — целевые границы upload/versioning, когда они будут созданы.

## Как работать

Перед редактированием:

1. Определи, меняешь ли ты текущий baseline или строишь целевой runtime.
2. Найди все callers изменяемого контракта.
3. Зафиксируй файлы в scope и acceptance criteria.
4. Не принимай неоговорённые продуктовые или архитектурные решения.
5. Для широкого рефакторинга сначала сделай один вертикальный exemplar.

После редактирования:

1. Запусти наиболее узкие релевантные тесты.
2. Выполни `python -m compileall agent api client helpers reports tools`.
3. При изменении Compose выполни `docker compose config`.
4. Не заявляй live-проверку OpenAI/1С, если она фактически не выполнялась.
5. Отчитайся: результат, файлы, проверки, ограничения и незакрытые решения.

## Запрещённые упрощения

- Не добавляй новые жёсткие имена файлов, листов, колонок или дат в prompts и skills.
- Не помещай всю бизнес-логику обратно в один Executor.
- Не дублируй workflow в API и LangGraph.
- Не создавай бесконечные retries и не скрывай последний невалидный результат.
- Не передавай Reporter необработанные данные с просьбой «самому разобраться».
- Не коммить raw бизнес-данные, credentials, внутренние URL или generated caches.
- Не сохраняй upload под client filename, не читай его целиком в memory и не принимай multipart completion за готовность к анализу.
- Не передавай в analysis filenames/paths вместо immutable dataset version ids.
- Не переписывай весь проект, не переходи на микросервисы и не переносись в `src/` без отдельного решения.
