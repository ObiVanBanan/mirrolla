---
paths:
  - "agent/skills/**/*.md"
  - "agent/skills/**/*.json"
  - "helpers/**/*.py"
  - "agent/planner.py"
---

# Правила аналитических skills

- Skill описывает бизнес-методику, а не текущую физическую выгрузку.
- Используй business concepts вместо обязательных column names.
- Конкретные filenames, row counts и date ranges допускаются только как явно помеченные examples, не как invariant.
- Разделяй `required_concepts` и `optional_concepts`.
- Для каждого вывода укажи, какие данные обязательны; отсутствие required data не компенсируется догадкой.
- Формулы, thresholds и priority rules должны быть однозначными и проверяемыми validator-ом.
- Reference helper показывает один корректный способ расчёта. Не требуй дословного копирования реализации.
- Planner выбирает только hypotheses, которые можно проверить по profiles/mapping, либо явно помечает их непроверяемыми.
- Не называй внутреннюю категорию «рынком», если внешних рыночных данных нет.
- Изменение смысла метрики требует обновить skill version, validator tests и документацию.
