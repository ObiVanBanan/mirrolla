---
paths:
  - "agent/**/*.py"
  - "api/**/*.py"
  - "client/**/*.py"
  - "helpers/**/*.py"
  - "reports/**/*.py"
  - "tools/**/*.py"
  - "tests/**/*.py"
---

# Проверка изменений

- Unit-тесты не требуют OpenAI key, VPN, 1С или production XLSX.
- Все внешние clients mock-нут на boundary, а не внутри бизнес-логики.
- Для нового parser/validator добавляй positive и negative fixtures.
- Для data flexibility добавляй fixture с переименованными колонками, другим sheet или несколькими файлами.
- Для workflow проверяй запрещённые transitions и повторную доставку, а не только happy path.
- Для retries проверяй точное число attempts и отсутствие лишнего upload.
- Не мокай component, который является предметом теста.
- Проверка изменения минимум: targeted tests + `python -m compileall agent api client helpers reports tools`.
- Live smoke test с OpenAI/1С отделён marker-ом и никогда не заявляется как пройденный без фактического запуска.
- Если test harness отсутствует, сначала добавь characterization test вокруг изменяемого поведения.

- Для upload проверяй streaming limit, path traversal, unsupported format, interrupted stream, checksum/dedupe и temporary cleanup.
- Для data selection проверяй unknown/not-ready/deleted versions и неизменность старого analysis после re-upload.
- Frontend smoke: несколько файлов, независимый progress, ready gating и точный payload `dataset_version_ids`.
