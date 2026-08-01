---
paths:
  - "agent/executor.py"
  - "agent/ci_runner.py"
  - "agent/runtime/**/*.py"
  - "agent/reporter.py"
---

# Code generation runtime

- Generated Python code остаётся основным аналитическим execution path.
- Prompt строится только из approved plan, versioned skill, profiles, semantic mapping, manifest, relevant references и output contract.
- Не вставляй глобальный static schema, который утверждает существование физических колонок.
- Передавай только релевантные helper modules/functions; не инжектируй весь `helpers/` автоматически.
- Сохраняй generated code, response id, attempt number, artifacts и validation report.
- Parser не должен превращать невалидный свободный текст в успешный количественный результат.
- Generic validator и skill validator не используют LLM.
- Repair получает только исходный manifest, предыдущий execution context и конкретные issue codes/messages.
- Максимум две repair-попытки после первоначальной. После исчерпания вернуть честный failed/partial result.
- Не перезагружай файлы и не создавай новый runner для semantic repair, если provider позволяет продолжить существующий context.
- Reporter получает только validated payload и не меняет числа.
