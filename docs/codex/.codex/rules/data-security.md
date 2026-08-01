---
paths:
  - "data/**"
  - ".env*"
  - "client/**/*.py"
  - "api/**/*.py"
  - "agent/**/*.py"
  - "compose*.yml"
  - "compose*.yaml"
---

# Данные и безопасность

- Не коммить реальные marketplace exports, персональные review texts, credentials, API tokens и внутренние endpoints.
- В публичных examples используй synthetic fixtures и нейтральные placeholder URL/usernames.
- Profiler может передавать LLM metadata и короткие безопасные examples, но не полные строки и не весь файл.
- Generated code не получает `.env`, credentials или network access без явной необходимости.
- Не логируй полные datasets, prompts с raw rows, passwords и полный generated code в production logs.
- Dataset version определяется checksum исходного файла; processing cache не заменяет provenance raw source.
- Удаление или перезапись raw source не происходит как побочный эффект анализа.
- Authentication, CORS и rate limits не ослабляются ради тестового удобства без явного dev-only режима.

- Upload читай потоково; используй server-generated storage key, size limit, checksum, temporary object и atomic commit.
- Не доверяй original filename, extension или browser MIME как безопасному path/type.
- Referenced DatasetVersion не удаляется физически.
- Browser storage не содержит raw file/base64.
