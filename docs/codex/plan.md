# Задача: добавить универсальный анализ произвольных датасетов без обязательного skill

Работай в репозитории `mirrolla` в текущей ветке.

Не ограничивайся составлением плана. Изучи код, внеси изменения, добавь тесты и выполни проверки.

Не спрашивай подтверждения между этапами. Если конкретное имя функции или расположение файла отличается от приведённого ниже, найди актуальное место через поиск по символам и адаптируй изменение под фактическую структуру проекта.

Не удаляй и не перезаписывай несвязанные пользовательские изменения. Не используй `git reset --hard`, `git checkout .`, массовое форматирование всего проекта или переписывание файлов без необходимости.

---

# 1. Цель изменения

Сейчас система воспринимает каждый аналитический запрос как один из четырёх специализированных skills.

Это неверно для запросов вида:

* «Сколько строк в этом CSV?»
* «Покажи записи со статусом failed».
* «Какие значения встречаются в колонке category?»
* «Найди дубликаты».
* «Посчитай долю успешных сопоставлений».
* «Проанализируй файл mapping_results.csv».
* «Какие колонки содержат пропуски?»

Подобные запросы не относятся к анализу снижения продаж, остатков, отзывов или роста портфеля. Они должны выполняться как обычный анализ приложенного датасета.

Новая архитектурная модель:

```text
Универсальный аналитический pipeline
+
необязательный специализированный skill
```

Skill должен быть дополнительной методологией, а не обязательным маршрутом.

Правильные варианты:

```text
general analysis
skill = null
```

или:

```text
specialized analysis
skill = sales-decline-analysis
```

---

# 2. Обязательные архитектурные ограничения

## 2.1. Не добавлять пятый skill

Запрещено добавлять:

```text
general-analysis
generic-analysis
free-analysis
custom-analysis
```

в `SkillType`.

Общий анализ — это базовая возможность системы, а не ещё один skill.

Существующие четыре значения `SkillType` должны сохраниться без переименования.

## 2.2. Не добавлять новый FastAPI endpoint

Не создавать:

```text
/api/v1/general-analysis
/api/v1/free-analysis
/api/v1/datasets/query
```

Использовать существующий endpoint создания анализа.

Клиент должен передавать:

* вопрос;
* `dataset_version_ids`.

Backend самостоятельно определяет, нужен ли skill.

## 2.3. Пока не добавлять direct execution

На этом этапе не создавать отдельную ветку:

```text
route → direct_execute
```

Общий анализ должен пройти через существующий pipeline:

```text
understand
→ route
→ plan
→ human approval
→ execute
→ report
```

Причина: сначала необходимо обеспечить корректность общего режима. Оптимизацию простых запросов через `ExecutionStrategy.DIRECT` можно сделать отдельной задачей после стабилизации.

## 2.4. Не переписывать весь Executor

Нельзя создавать второй независимый Executor для общего анализа.

Должен остаться один Executor с двумя режимами:

```text
skill is not None
    → универсальные инструкции + инструкции skill

skill is None
    → только универсальные инструкции
```

## 2.5. Не ломать legacy-режим

Существующие сценарии четырёх skills должны продолжить работать.

Не удалять:

* существующие skills;
* HITL;
* demo/legacy workflow, если он используется тестами;
* сохранение provenance;
* точное разрешение `DatasetVersion`;
* checksum/blob verification;
* execution manifest;
* attached execution.

---

# 3. Перед изменениями

Выполни:

```bash
git status --short
git branch --show-current
```

Запомни все уже изменённые файлы. Не откатывай их.

Найди все места, где предполагается обязательный skill:

```bash
rg -n "SkillType" .
rg -n "routing\.skill|plan\.skill|result\.skill" agent api application infrastructure tests ui
rg -n "skill\.value|skill_id" agent api application infrastructure tests ui
rg -n "_load_skill_md|load_skill_metadata|SKILL\.md" agent tests
rg -n "RoutingResult|AnalysisPlan|ExecutionResult" agent api tests
```

Запусти базовые тесты до редактирования:

```bash
python -m pytest -q
```

Если полный набор уже падает, сохрани список исходных ошибок. Не исправляй несвязанные проблемы, если они не мешают задаче.

---

# 4. Изменение доменных контрактов

Основной файл предположительно:

```text
agent/schemas.py
```

Проверь фактическое расположение моделей.

## 4.1. Добавить режим анализа

Добавь enum:

```python
class AnalysisMode(str, Enum):
    GENERAL = "general"
    SPECIALIZED = "specialized"
```

Не называй специализированный режим `skill`, чтобы не смешивать вид анализа и идентификатор конкретного skill.

## 4.2. Изменить RoutingResult

Целевая семантика:

```python
class RoutingResult(BaseModel):
    analysis_mode: AnalysisMode
    skill: SkillType | None = None
    skill_confidence: float = 0.0

    product_codes: list[str] = Field(default_factory=list)
    period_days: int | None = None
```

Сохрани остальные существующие поля модели.

Добавь проверку согласованности:

```text
analysis_mode == general
    → skill обязан быть null

analysis_mode == specialized
    → skill обязан быть задан
```

Допустимо реализовать это через `model_validator`.

Нельзя автоматически подставлять `sales-decline-analysis`, когда `skill` отсутствует.

`skill_confidence` должен находиться в диапазоне от `0.0` до `1.0`.

## 4.3. Изменить AnalysisPlan

Добавь:

```python
analysis_mode: AnalysisMode
skill: SkillType | None = None
```

Сохрани существующую структуру гипотез, approval и остальные поля.

Для общего анализа разрешается одна гипотеза. Не требуй всегда 3–5 гипотез.

Простой запрос:

```text
Сколько строк в файле?
```

не должен искусственно превращаться в три аналитические гипотезы.

Если ограничение количества гипотез задано через Pydantic:

```python
min_length=3
```

замени его на подходящий минимум, например:

```python
min_length=1
```

В prompt Planner оставь рекомендацию создавать несколько гипотез только для действительно сложного исследования.

## 4.4. Изменить ExecutionResult

Добавь:

```python
analysis_mode: AnalysisMode
skill: SkillType | None = None
```

Существующие специализированные findings сохрани.

Для общего режима должно быть допустимо:

```python
findings=[]
```

при условии, что присутствует содержательный `answer` или `summary`.

Не заставляй общий анализ генерировать:

* `entity_id`;
* приоритет товара;
* процент падения продаж;
* производственную рекомендацию;
* отзыв;
* SKU;

если этого не требует вопрос пользователя.

## 4.5. Обратная совместимость

В базе или сохранённых JSON могут находиться старые планы без `analysis_mode`.

Добавь безопасную совместимость:

```text
если analysis_mode отсутствует и skill задан
    → считать режим specialized

если analysis_mode отсутствует и skill отсутствует
    → считать режим general
```

Не проводи ненужную миграцию базы, если колонка `skill` уже допускает `NULL`.

Добавь отдельный тест загрузки старого JSON с заданным skill и без `analysis_mode`.

---

# 5. Исправление Router

Основной файл предположительно:

```text
agent/router.py
```

## 5.1. Изменить системный prompt

Удалить требование:

```text
Классифицируй строго по четырём skill-классам
```

Новый смысл prompt:

```text
Ты определяешь, нужен ли вопросу специализированный skill.

Выбирай specialized только тогда, когда намерение пользователя явно
соответствует одному из доступных skills.

Для обычных операций над приложенным CSV/XLSX/JSON выбирай general.

В general:
- skill = null;
- skill_confidence = 0 или низкое значение.

Не выбирай skill только потому, что система требует непустое значение.
Не пытайся трактовать любой числовой датасет как продажи.
```

Добавь примеры.

### General

```json
{
  "question": "Сколько строк в mapping_results.csv?",
  "analysis_mode": "general",
  "skill": null
}
```

```json
{
  "question": "Покажи записи, где status не равен mapped",
  "analysis_mode": "general",
  "skill": null
}
```

```json
{
  "question": "Найди дубликаты и пропуски",
  "analysis_mode": "general",
  "skill": null
}
```

### Specialized

```json
{
  "question": "Почему упали продажи артикула 123?",
  "analysis_mode": "specialized",
  "skill": "sales-decline-analysis"
}
```

```json
{
  "question": "Какие позиции скоро закончатся?",
  "analysis_mode": "specialized",
  "skill": "inventory-production-planning"
}
```

Используй реальные значения существующего `SkillType`, а не значения из этого текста, если они отличаются.

## 5.2. Исправить keyword fallback

Найди fallback, который начисляет баллы skills.

Текущее ошибочное поведение:

```text
если ни один skill не набрал баллы
    → выбрать sales-decline-analysis
```

Новое поведение:

```python
if best_score <= 0:
    return RoutingResult(
        analysis_mode=AnalysisMode.GENERAL,
        skill=None,
        skill_confidence=0.0,
        ...
    )
```

Если найдено явное совпадение:

```python
return RoutingResult(
    analysis_mode=AnalysisMode.SPECIALIZED,
    skill=best_skill,
    skill_confidence=calculated_confidence,
    ...
)
```

Fallback обязан работать без LLM и API-ключа.

## 5.3. Передавать Router контекст датасетов

Router должен видеть не только вопрос, но и профили выбранных файлов.

Измени публичный контракт примерно так:

```python
def route_sync(
    question: str,
    dataset_context: Sequence[ResolvedDatasetInput] | None = None,
) -> RoutingResult:
    ...
```

Не создавай жёсткую зависимость от конкретного класса, если это нарушает слои. Допустимо передавать заранее сериализованный профиль.

В prompt достаточно передать:

* имя файла;
* формат;
* sheet/table name;
* названия колонок;
* inferred types;
* количество строк, если известно.

Не передавай в Router весь файл.

Router должен учитывать правило:

```text
Skill выбирается по намерению пользователя.
Профиль датасета используется как дополнительный сигнал.
Отсутствие специализированного skill не является ошибкой.
```

Не создавай сложный semantic mapper в рамках этой задачи.

---

# 6. Изменить порядок операций в API

Найди обработчик создания анализа.

Сейчас Router может вызываться раньше разрешения `dataset_version_ids`. Исправь порядок:

```text
1. Принять question и dataset_version_ids.
2. Разрешить точные DatasetVersion.
3. Проверить profile/blob/checksum.
4. Сформировать dataset_context.
5. Передать question + dataset_context в Router.
6. Передать routing + dataset_context в Planner.
7. Сохранить план.
```

Не загружай глобальные demo-файлы для attached execution.

Все обращения вида:

```python
plan.skill.value
routing.skill.value
result.skill.value
```

замени безопасной логикой:

```python
skill_value = plan.skill.value if plan.skill is not None else None
```

Лучше создать небольшой helper, если одинаковая проверка используется во многих местах.

Убедись, что `NULL` действительно сохраняется в колонку `skill`.

API-ответ общего анализа должен содержать:

```json
{
  "analysis_mode": "general",
  "skill": null
}
```

Проверь также endpoint пересмотра плана. Он не должен восстанавливать случайный skill при revise.

---

# 7. Изменить Planner

Основной файл:

```text
agent/planner.py
```

## 7.1. Skill должен быть optional overlay

Нельзя безусловно делать:

```python
skill_md = _load_skill_md(routing.skill)
```

Сделай:

```python
skill_md = (
    _load_skill_md(routing.skill)
    if routing.skill is not None
    else ""
)
```

Добавляй секцию с методикой skill в prompt только при наличии skill.

### Specialized prompt

```text
Универсальные правила анализа
+
профили приложенных датасетов
+
методика выбранного skill
+
вопрос пользователя
```

### General prompt

```text
Универсальные правила анализа
+
профили приложенных датасетов
+
вопрос пользователя
```

В general prompt не должно быть:

* имени случайного skill;
* требований искать продажи;
* требований искать остатки;
* требований искать отзывы;
* ссылок на demo-схему;
* выдуманных обязательных колонок.

## 7.2. Универсальные правила Planner

Добавь в базовый prompt:

```text
Работай только с приложенными DatasetVersion.

Используй только реально существующие файлы, таблицы и колонки,
указанные в профилях.

Не придумывай названия колонок.

Определи минимальный набор операций, необходимый для ответа.

Для простого запроса создавай одну конкретную гипотезу или задачу.

Для сложного анализа допускается несколько гипотез.

Если данных недостаточно, явно укажи ограничение.
Не подменяй недостающие данные demo-файлами.
```

## 7.3. General fallback plan

Fallback должен работать без LLM.

Для общего attached-запроса сформируй план примерно следующего смысла:

```json
{
  "analysis_mode": "general",
  "skill": null,
  "objective": "Ответить на вопрос по прикреплённым данным",
  "hypotheses": [
    {
      "id": "H1",
      "title": "Выполнить запрошенную операцию над прикреплённым датасетом",
      "method": "Прочитать выбранные версии, проверить реальные колонки и выполнить фильтрацию, агрегацию, подсчёт или проверку, указанную в вопросе",
      "datasets": ["точные идентификаторы приложенных версий"]
    }
  ]
}
```

Не используй буквальный универсальный метод, если из вопроса можно определить операцию точнее.

Примеры:

```text
«Сколько строк?»
→ count rows

«Покажи status=failed»
→ filter rows by existing status column

«Найди дубликаты»
→ duplicate detection

«Какие колонки пустые?»
→ null count by column
```

## 7.4. Не разрешать LLM менять маршрут

После structured output проверь согласованность результата с Router.

Planner не должен самостоятельно подставить skill, если Router вернул general.

Принудительно нормализуй:

```python
plan.analysis_mode = routing.analysis_mode
plan.skill = routing.skill
```

Используй безопасный для Pydantic способ, например `model_copy(update=...)`.

---

# 8. Изменить execution manifest

Найди модель manifest, предположительно:

```text
agent/runtime/execution_manifest.py
```

Измени:

```python
skill_id: str
```

на:

```python
skill_id: str | None = None
analysis_mode: AnalysisMode
```

Если импорт доменного enum создаёт циклическую зависимость, в manifest допустимо использовать:

```python
analysis_mode: Literal["general", "specialized"]
```

Обнови builder manifest.

Обязательные свойства attached execution должны сохраниться:

* точные `dataset_version_id`;
* путь к materialized temporary file;
* checksum;
* profile;
* provenance;
* отсутствие fallback на глобальные demo-файлы.

Manifest общего анализа должен выглядеть по смыслу так:

```json
{
  "analysis_mode": "general",
  "skill_id": null,
  "datasets": [...]
}
```

Добавь тест сериализации и десериализации такого manifest.

---

# 9. Изменить Executor

Основной файл:

```text
agent/executor.py
```

Сначала найди все обращения:

```python
plan.skill.value
_load_skill_md(plan.skill)
load_skill_metadata(plan.skill)
```

## 9.1. Attached execution должен иметь приоритет

Если присутствует attached execution manifest, Executor обязан работать с точными materialized files независимо от наличия skill.

Логика должна быть такой:

```python
if attached_execution_manifest is not None:
    return execute_attached(...)

if plan.skill is not None:
    return execute_legacy_skill(...)

return controlled_no_data_result(...)
```

Не допускай, чтобы `skill=None` случайно отправлял attached-анализ в legacy/demo runtime.

## 9.2. Условно загружать SKILL.md

Запрещено безусловно загружать skill.

Используй блок:

```python
skill_section = ""

if plan.skill is not None:
    skill_section = (
        "## Дополнительная методика skill\n"
        + _load_skill_md(plan.skill)
    )
```

Для general этот блок полностью отсутствует.

## 9.3. Добавить универсальные инструкции Executor

В attached prompt общего режима добавь требования:

```text
Ты анализируешь реальные приложенные файлы.

Работай только с путями из execution manifest.

Перед выполнением:
1. Определи формат каждого файла.
2. Безопасно прочитай CSV/XLSX/JSON.
3. Проверь реальные названия колонок и типы.
4. Не используй колонку, пока не убедишься, что она существует.
5. Выполни именно операцию из вопроса и плана.
6. Не применяй бизнес-методику, если skill отсутствует.
7. Не придумывай продажи, остатки, SKU, даты или отзывы.
8. Верни понятный ответ на русском языке.
```

Для CSV обработай практические случаи:

* UTF-8 и UTF-8 BOM;
* распространённые разделители `,`, `;`, tab;
* пустой файл;
* файл только с заголовком;
* дублирующиеся имена колонок;
* числовые значения, прочитанные как строки.

Не нужно писать новый универсальный framework чтения файлов, если такие функции уже присутствуют. Переиспользуй существующий materialization/CI runtime.

## 9.4. Общий контракт результата

Для general разреши результат:

```json
{
  "answer_status": "answered",
  "answer": "В файле 1842 строки.",
  "findings": [],
  "hypothesis_results": [],
  "limitations": []
}
```

Для фильтрации допускается:

```json
{
  "answer_status": "answered",
  "answer": "Найдено 17 строк со статусом failed. Ниже приведены первые 10...",
  "findings": [],
  "limitations": [
    "В ответе показаны первые 10 строк из 17."
  ]
}
```

Не заставляй результат общего анализа соответствовать специализированным полям findings.

## 9.5. Валидация результата

Измени валидатор так, чтобы он принимал:

```python
skill: SkillType | None
analysis_mode: AnalysisMode
```

Правила:

### General

Обязательно:

* `answer_status`;
* непустой `answer` или `summary`;
* `limitations` как список;
* корректный JSON.

Необязательно:

* findings;
* SKU;
* recommended action;
* change percentage.

### Specialized

Сохранить существующие skill-specific проверки.

Нельзя полностью отключать валидацию для general.

## 9.6. Ошибки выполнения

Если вопрос ссылается на несуществующую колонку:

```text
Покажи status=failed
```

но `status` отсутствует, результат должен быть контролируемым:

```json
{
  "answer_status": "not_enough_data",
  "answer": "В приложенном датасете нет колонки status.",
  "limitations": [
    "Доступные колонки: source_name, target_name, confidence."
  ]
}
```

Не допускать:

* traceback пользователю;
* подстановку похожей колонки без объяснения;
* переход к случайному skill;
* чтение demo-датасета.

---

# 10. Изменить Reporter

Найди Reporter и его метод синтеза ответа.

Он должен принимать:

```python
skill: SkillType | None
analysis_mode: AnalysisMode
```

## General

Reporter обязан:

* отвечать прямо на вопрос;
* сохранять рассчитанные числа;
* не добавлять бизнес-рекомендации без запроса;
* не превращать ответ в отчёт о снижении продаж;
* явно сообщать ограничения;
* не придумывать контекст Mirrolla, если его нет в данных.

## Specialized

Существующее поведение сохранить.

Не загружать `SKILL.md`, если `skill is None`.

---

# 11. Проверить LangGraph

Не добавляй новый endpoint и не добавляй пятый skill-node.

Существующий Router node должен иметь возможность вернуть:

```python
RoutingResult(
    analysis_mode=AnalysisMode.GENERAL,
    skill=None,
)
```

Остальные nodes должны принять такое состояние без ошибки:

```text
route
→ plan
→ human approval
→ execute
→ report
```

Проверь:

* сериализацию state;
* checkpoint;
* resume после approval;
* revise;
* reject;
* загрузку старого checkpoint.

Если state содержит отдельное обязательное поле `skill`, сделай его nullable или получай из `routing`.

---

# 12. Исправить UI только в необходимых местах

Не делай редизайн интерфейса.

Найди все места, где UI предполагает, что `skill` всегда строка.

Обработай `null`.

Вместо пустого значения или ошибки показывай:

```text
Режим: Общий анализ
```

Для specialized:

```text
Режим: Специализированный анализ
Skill: <название>
```

Не выводи:

```text
Skill: null
Skill: undefined
```

Не блокируй approve из-за отсутствующего skill.

---

# 13. Тесты Router

Добавь отдельные unit tests.

LLM и внешняя сеть не должны требоваться.

## 13.1. General fallback

```python
question = "Сколько строк в mapping_results.csv?"
```

Ожидание:

```python
result.analysis_mode == AnalysisMode.GENERAL
result.skill is None
```

## 13.2. General filter

```python
question = "Покажи записи, где status не равен mapped"
```

Ожидание:

```python
result.analysis_mode == AnalysisMode.GENERAL
result.skill is None
```

## 13.3. General data quality

```python
question = "Найди дубликаты и пустые значения"
```

Ожидание: general без skill.

## 13.4. Existing sales skill

```python
question = "Почему упали продажи артикула 123?"
```

Ожидание: существующий skill анализа падения продаж.

## 13.5. Existing inventory skill

```python
question = "Какие товары скоро закончатся и что заказать?"
```

Ожидание: существующий inventory/production skill.

## 13.6. Неизвестный текст

```python
question = "Проанализируй этот файл"
```

Ожидание: general, а не sales fallback.

---

# 14. Тесты Planner

Создай небольшой фиктивный attached dataset profile:

```text
filename: mapping_results.csv
columns:
- source_name
- target_name
- status
- confidence
```

Проверь:

1. General plan имеет `skill is None`.
2. План ссылается только на прикреплённую версию.
3. В плане нет demo-файлов.
4. В плане нет требований анализировать продажи.
5. Для вопроса о количестве строк создаётся одна задача.
6. `_load_skill_md` не вызывается.
7. Fallback без LLM также возвращает корректный general plan.

Используй monkeypatch/mock для проверки отсутствия вызова skill loader.

---

# 15. Тесты manifest и Executor

## 15.1. Manifest

Проверь:

```python
manifest.analysis_mode == "general"
manifest.skill_id is None
```

Manifest должен успешно сериализоваться.

## 15.2. Prompt

Для general prompt:

* присутствует имя `mapping_results.csv`;
* присутствуют реальные колонки;
* присутствует вопрос;
* отсутствует `sales-decline-analysis`;
* отсутствует текст `SKILL.md`;
* отсутствуют имена demo-файлов.

## 15.3. Validation

Результат:

```json
{
  "answer_status": "answered",
  "answer": "В файле 25 строк.",
  "findings": [],
  "limitations": []
}
```

должен пройти general validation.

Тот же результат не должен автоматически считаться валидным для skill, если специализированный skill требует дополнительные поля.

## 15.4. Missing column

Проверь controlled response при запросе отсутствующей колонки.

---

# 16. API integration test

Добавь интеграционный тест следующего сценария:

1. Создать workspace.
2. Загрузить `mapping_results.csv`.
3. Получить конкретный `dataset_version_id`.
4. Создать analysis:

```json
{
  "question": "Сколько строк в этом файле?",
  "dataset_version_ids": ["<version-id>"]
}
```

5. Проверить ответ создания:

```text
analysis_mode = general
skill = null
```

6. Проверить сохранённый `plan_json`:

```text
analysis_mode = general
skill = null
```

7. Проверить значение в базе:

```text
skill IS NULL
```

8. Approve plan.
9. Запустить attached execution с замоканным CI/LLM, если реальный вызов требует внешний сервис.
10. Проверить, что результат содержит ответ и execution provenance.
11. Проверить, что не использовались глобальные demo-файлы.

Добавь второй сценарий:

```text
Покажи строки, где status = failed
```

Он также должен идти через general.

---

# 17. Регрессионные тесты

Обязательно проверить существующие четыре skills.

Минимум по одному маршруту на каждый skill.

Проверить:

* Router возвращает прежний SkillType.
* Planner загружает соответствующий `SKILL.md`.
* Executor получает skill instructions.
* specialized validation продолжает работать.
* API сохраняет строковое значение skill.
* management report не ломается.

---

# 18. Команды проверки

Сначала запускай узкие тесты:

```bash
python -m pytest tests/api -q
python -m pytest tests/runtime -q
python -m pytest tests -k "router or planner or executor or manifest" -q
```

Если структура тестов отличается, выбери фактические пути.

Затем:

```bash
python -m pytest -q
```

Дополнительно:

```bash
python -m compileall agent api application infrastructure
```

Если в проекте настроены инструменты:

```bash
ruff check .
mypy agent api application infrastructure
```

Не добавляй новые линтеры в зависимости только ради этой задачи.

---

# 19. Ручная проверка

Запусти приложение существующим способом.

Проверь через UI:

1. Загрузить `mapping_results.csv`.
2. Открыть его в «Мои данные».
3. Создать вопрос:

```text
Сколько строк в этом файле?
```

Ожидание:

```text
Режим: Общий анализ
```

Skill отсутствует.

4. Approve plan.
5. Получить фактическое количество строк.
6. Создать вопрос:

```text
Покажи строки, где status не равен mapped
```

7. Убедиться, что анализирует именно приложенную версию.
8. Убедиться, что в ответе нет рассуждений о падении продаж.
9. Создать специализированный вопрос по подходящему sales dataset.
10. Убедиться, что соответствующий skill продолжает применяться.

---

# 20. Definition of Done

Задача завершена только при выполнении всех условий:

* `SkillType` по-прежнему содержит только существующие четыре skills.
* Router может вернуть `skill=None`.
* Отсутствие keyword match больше не приводит к sales fallback.
* General запрос проходит через существующий LangGraph.
* Новый FastAPI endpoint не добавлен.
* Новый general skill не добавлен.
* Planner работает без `SKILL.md`.
* Executor работает без `SKILL.md`.
* Reporter работает без skill.
* Manifest поддерживает `skill_id=null`.
* API сохраняет `NULL` в поле skill.
* UI корректно отображает общий режим.
* Произвольный attached CSV используется как источник данных.
* Demo-файлы не используются в attached general execution.
* Старые специализированные сценарии не сломаны.
* Добавлены unit и integration tests.
* Полный набор тестов запущен.
* Все внесённые изменения перечислены в итоговом отчёте.

---

# 21. Что не делать

Не делать следующее:

* не добавлять `GENERAL` в `SkillType`;
* не создавать папку `skills/general`;
* не копировать один из существующих `SKILL.md`;
* не выбирать sales skill в качестве default;
* не исправлять проблему только в UI;
* не скрывать skill на фронтенде, оставляя его обязательным в backend;
* не заменять `None` пустой строкой;
* не использовать `"unknown"` как фиктивный skill;
* не отключать Pydantic validation;
* не отключать execution manifest;
* не возвращаться к глобальным demo-файлам;
* не загружать весь датасет в prompt Router;
* не переписывать LangGraph с нуля;
* не добавлять direct execution в эту задачу;
* не менять несвязанные части проекта;
* не удалять тесты, которые начали падать после изменения.

---

# 22. Формат итогового отчёта

После выполнения выдай отчёт:

```text
OUTCOME

Кратко:
- Что было изменено архитектурно.
- Как теперь определяется general/specialized.
- Как выполняется анализ без skill.

CHANGED FILES

- path/to/file.py
  - конкретные изменения

- path/to/test.py
  - какие сценарии проверяются

BEHAVIOR

General:
- пример маршрутизации
- пример плана
- пример результата

Specialized:
- что осталось без изменений

TESTS

- точная команда
- точный результат
- количество passed/failed/skipped

MANUAL CHECK

- что проверено через UI/API
- фактический результат

REMAINING RISKS

- только реальные оставшиеся ограничения
- без выдуманных будущих задач
```

Не утверждай, что тест или ручная проверка прошли, если они фактически не запускались.

Если полный набор тестов падает из-за существующей несвязанной проблемы, отдельно укажи:

* какие тесты падали до изменений;
* какие появились после изменений;
* почему ошибка не относится к этой задаче.

Главный ожидаемый результат:

```text
mapping_results.csv
+
обычный вопрос к его содержимому
+
skill = null
+
анализ реального приложенного файла
+
нормальный ответ без случайной бизнес-методики
```
