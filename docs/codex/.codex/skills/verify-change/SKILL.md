---
name: verify-change
description: "Независимо проверить уже выполненное изменение Mirrolla, запустить дешёвые проверки и найти интеграционные регрессии."
disable-model-invocation: true
---

# Verify change

Проверь `$ARGUMENTS` как независимый reviewer.

1. Получи исходный brief/acceptance criteria. Без них не подменяй цель своим представлением.
2. Прочитай diff и callers изменённых contracts.
3. Прочитай `REVIEW.md` и применимые `.claude/rules/`.
4. Запусти дешёвые targeted checks самостоятельно.
5. Ищи прежде всего неправильное поведение, потерю provenance, static schema assumptions, workflow duplication, непроверенные external boundaries и ложные claims о тестах.
6. Не исправляй код.

Формат:

```text
VERDICT: PASS | PASS WITH NITS | FAIL

EVIDENCE
- проверка — результат

FINDINGS
1. severity — path:line — конкретный отказ

UNVERIFIED
Что осталось непроверенным и почему.

FAILURE TYPE
SPECIFICATION | CAPABILITY | NONE
```
