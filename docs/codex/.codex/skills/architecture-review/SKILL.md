---
name: architecture-review
description: "Проверить план, diff или набор файлов Mirrolla против зафиксированной продуктовой и целевой архитектуры."
disable-model-invocation: true
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash(git status *)
  - Bash(git diff *)
---

# Architecture review

Проведи read-only review аргумента `$ARGUMENTS`.

1. Прочитай `CLAUDE.md`.
2. Прочитай `docs/agent/DECISIONS.md` и релевантные разделы `CURRENT_ARCHITECTURE.md`/`TARGET_ARCHITECTURE.md`.
3. Начни с исходной цели изменения, а не с diff.
4. Проверь:
   - не заменена ли code generation фиксированными tools;
   - не добавлена ли static physical schema;
   - сохранены ли provenance, validation и honest limitations;
   - не появился ли второй workflow;
   - не получил ли Reporter аналитические обязанности;
   - покрыты ли boundary и negative cases.
5. Не исправляй файлы.

Ответ:

```text
VERDICT: PASS | PASS WITH NITS | FAIL

ARCHITECTURE FIT
Краткий вывод.

FINDINGS
1. severity — path:line
   Нарушение и сценарий отказа.

MISSING EVIDENCE
Что нельзя подтвердить.

FAILURE TYPE
SPECIFICATION | CAPABILITY | NONE
```
