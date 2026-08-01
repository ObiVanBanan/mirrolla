---
name: implement-slice
description: "Реализовать одно узко ограниченное изменение Mirrolla по готовому brief, не принимая новых архитектурных решений."
disable-model-invocation: true
---

# Implement one slice

Выполни задачу из `$ARGUMENTS` или указанного brief-файла.

## До редактирования

1. Прочитай `CLAUDE.md` и path-scoped rules для будущих файлов.
2. Прочитай только релевантные документы из `docs/agent/`.
3. Выдели:
   - цель;
   - решения, уже принятые за тебя;
   - файлы в scope;
   - out of scope;
   - acceptance criteria;
   - verification commands.
4. Найди callers изменяемых contracts.
5. Если brief оставляет архитектурный fork, остановись и перечисли решение, которое должен принять человек/архитектор.

## Реализация

- Делай минимальное полное изменение.
- Не добавляй TODO вместо требуемого поведения.
- Не исправляй соседние проблемы вне scope.
- Следуй существующему exemplar, если он указан.
- Сохраняй backward compatibility, если brief явно не разрешает breaking change.

## Проверка

- Запусти targeted tests.
- Выполни compile/import check.
- Сверь каждый acceptance criterion с фактическим доказательством.
- Не заявляй проверки, которые не запускал.

## Отчёт

```text
OUTCOME
Что теперь работает.

FILES CHANGED
- path — изменение

VERIFICATION
- команда — фактический результат

ACCEPTANCE CRITERIA
- [x] критерий — доказательство
- [ ] критерий — причина

OPEN ITEMS
Только реальные остатки или решения.
```
