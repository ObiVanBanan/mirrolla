# Шаблон узкой задачи для агента

Используй этот формат, когда работу выполняет более слабая модель.

## Контекст

Кратко опиши текущий компонент, его callers и проблему. Укажи релевантные документы из `docs/agent/`.

## Цель

Одно проверяемое изменение, сформулированное как новое поведение системы.

## Уже принятые решения

Перечисли решения, которые исполнителю запрещено переоткрывать.

## Файлы в scope

- точные пути;
- разрешено ли создавать новые файлы;
- какие contracts можно менять.

## Вне scope

Явно перечисли соседние улучшения, которые делать нельзя.

## Эталон

Укажи существующий файл/тест/pattern, который нужно повторить. Если эталона нет и задача требует придумать новый cross-cutting pattern, её должен сначала решить сильный архитектор.

## Acceptance criteria

Каждый критерий должен быть бинарно проверяемым.

Пример:

- [ ] `SkillLoader` загружает metadata и `SKILL.md`.
- [ ] missing metadata возвращает typed error.
- [ ] Planner V1 не изменил поведение.
- [ ] unit tests проходят без OpenAI key.

## Verification

Перечисли точные команды и ожидаемые признаки успеха.

## Формат отчёта

```text
OUTCOME
FILES CHANGED
VERIFICATION
ACCEPTANCE CRITERIA
OPEN ITEMS
```

## Stop conditions

Исполнитель обязан остановиться, если:

- требуется выбрать новую архитектуру;
- acceptance criteria противоречат коду или друг другу;
- задача выходит за указанные файлы;
- отсутствует необходимый contract/fixture;
- безопасное решение требует новых credentials или raw production data.


## Дополнение для upload/data задач

Обязательно укажи:

- какая фаза `FILE_WORKSPACE_PLAN.md` выполняется;
- допустимые formats и max size;
- status transition DatasetVersion;
- storage/repository boundaries;
- exact API request/response;
- как analysis получает version ids;
- negative tests для path traversal, oversize и not-ready version.
