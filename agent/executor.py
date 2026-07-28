"""
agent/executor.py — Executor: выполнение плана анализа через OpenAI Code Interpreter.

Поток (Hosted Code Interpreter):
    AnalysisPlan → ci_runner.CIRunner → Assistant (code_interpreter tool)
    → загрузка файлов в OpenAI → запуск → скачивание графиков → Results

Преимущества hosted CI перед локальным sandbox:
- Code Interpreter сам пишет, запускает и исправляет Python код
- Не зависит от локального venv / pandas версии
- Sandbox изолирован, не может сломать локальное окружение
- Сам скачивает и прикрепляет графики (PNG)

Запуск:
    python -m agent.executor "Почему упали продажи ЦБ-00007397?"
"""

import os
import sys
import json
import re
import math

from dotenv import load_dotenv

from agent.runtime.execution_manifest import ExecutionManifest
from agent.schemas import (
    SkillType,
    AnalysisPlan,
    ExecutionDatasetMetadata,
    ExecutionMetadata,
    ExecutionResult,
    Finding,
    HypothesisResult,
)
from agent.planner import plan as generate_plan

load_dotenv()

MODEL_NAME = os.getenv("EXECUTOR_MODEL", "gpt-4o-mini")

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PREPARED_DIR = os.path.join(DATA_DIR, "prepared")
CHARTS_DIR = os.path.join(DATA_DIR, "charts")
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


# === Файлы данных для загрузки в Code Interpreter ===

def _collect_data_files(plan: AnalysisPlan) -> list[str]:
    """
    Собрать пути к файлам, нужным для анализа, на основе датасетов из гипотез.

    Args:
        plan: план анализа.

    Returns:
        list[str]: абсолютные пути к файлам для загрузки в OpenAI.
    """
    all_datasets = set()
    for h in plan.hypotheses:
        all_datasets.update(h.datasets)

    files = []

    # sales / reviews_ozon — Ozon xlsx (3 файла)
    if "sales" in all_datasets or "reviews_ozon" in all_datasets:
        for name in ["озон 17.03-16.04.xlsx", "озон 17.04-16.05.xlsx", "озон 17.05-16.06.xlsx"]:
            path = os.path.join(DATA_DIR, name)
            if os.path.exists(path):
                files.append(path)

    # reviews_wb — WB отзывы
    if "reviews_wb" in all_datasets:
        path = os.path.join(DATA_DIR, "Отзывы ВБ 17.03-17.06.2026.xlsx")
        if os.path.exists(path):
            files.append(path)

    # categories — каталог 1С (products.json)
    if "categories" in all_datasets:
        path = os.path.join(PREPARED_DIR, "products.json")
        if os.path.exists(path):
            files.append(path)

    # stocks — balances.json (pre-fetched из 1С, см. _prefetch_balances)
    if "stocks" in all_datasets:
        balances_path = os.path.join(PREPARED_DIR, "balances.json")
        if os.path.exists(balances_path):
            files.append(balances_path)

    return files


def _prefetch_balances(plan: AnalysisPlan) -> tuple[bool, str]:
    """
    Pre-fetch остатки из 1С и сохранить в data/prepared/balances.json.

    Code Interpreter sandbox не имеет доступа к VPN/1С, поэтому балансы
    забираем локально и загружаем как файл.

    Returns:
        (success, message): True если балансы получены и сохранены.
    """
    all_datasets = set()
    for h in plan.hypotheses:
        all_datasets.update(h.datasets)

    if "stocks" not in all_datasets:
        return True, "stocks не требуются"

    try:
        from client.onec_client import OneCClient

        print("  [Executor] Pre-fetch остатков из 1С (VPN)...")
        client = OneCClient()
        balances = client.get_balances()

        if balances.empty:
            return False, "1С вернул пустой ответ"

        # Сохранить в JSON
        balances_path = os.path.join(PREPARED_DIR, "balances.json")
        os.makedirs(PREPARED_DIR, exist_ok=True)
        balances_data = balances.to_dict(orient="records")
        with open(balances_path, "w", encoding="utf-8") as f:
            json.dump(balances_data, f, ensure_ascii=False, indent=2)

        print(f"  [Executor] ✅ Балансы: {len(balances)} товаров → {balances_path}")
        return True, f"{len(balances)} товаров"

    except Exception as e:
        print(f"  [Executor] ⚠ 1С недоступен: {e}")
        print("  [Executor] → гипотезы по остаткам будут помечены как непроверяемые")
        return False, f"1С недоступен: {e}"


# === Схема данных для prompt ===

DATA_SCHEMA = """
## Файлы данных (загружены в sandbox как attachments):

### Ozon — продажи и отзывы (3 файла: ozon_1.xlsx, ozon_2.xlsx, ozon_3.xlsx)
Колонки (все 3 файла идентичны):
- Артикул (str): ЦБ-XXXXXXXX / ФР-XXXXXXXX — КЛЮЧ
- SKU (int): SKU Ozon
- Название товара (str)
- Номер заказа (str)
- Статус получения (str): "Получен" / "Отменен"
- Текст отзыва (str): ~80% пусто
- Дата публикации (str, ISO 8601 UTC): "2026-03-16T21:00:07Z"
- Статус отзыва (str): "Новый" / "Обработан" / "Просмотрен"
- Оценка (int): 1-5
- Количество фото (int)
- Количество видео (int)
- Количество ответов на отзыв (int)

Каждая строка = заказ + опциональный отзыв.
Период данных: 2026-03-16 → 2026-06-16 (≈92 дня).

### WB — отзывы (wb_reviews.xlsx, лист "feedbacks", 4132 строк)
Колонки:
- ID отзыва (str)
- Дата (datetime)
- Артикул продавца (str): ЦБ-XXXXXXXX / ФР-XXXXXXXX — КЛЮЧ
- Артикул WB (int)
- Количество звезд (int): 1-5
- Бренд (str)
- Текст отзыва (str): 77% пусто
- Достоинства (str)
- Недостатки (str)
- Регион (str): ru, by, kz, ...
- Штрихкод (int): GTIN

### Каталог 1С (products.json, 3854 товара)
Поля: code, name, isGroup, gtin, articleOzon, articleWb, productType, brand, ...

### Балансы 1С (balances.json) — ТОЛЬКО если загружен
Поля: product_code, name, balance
⚠️ Если balances.json НЕ загружен — 1С недоступен, гипотезы по остаткам не проверяемы.
"""

# === Чтение SKILL.md ===

def _load_skill_md(skill: SkillType) -> str:
    """Загрузить SKILL.md."""
    skill_path = os.path.join(SKILLS_DIR, skill.value, "SKILL.md")
    if not os.path.exists(skill_path):
        return ""
    with open(skill_path, "r", encoding="utf-8") as f:
        return f.read()


# === Универсальные правила анализа (общие для всех skill'ов) ===

UNIVERSAL_ANALYSIS_INSTRUCTIONS = """## Общие правила анализа

1. Сначала изучи структуру всех загруженных файлов:
   - имена файлов (через os.listdir('/mnt/data/'));
   - названия колонок (df.columns);
   - типы данных;
   - диапазоны дат;
   - количество строк;
   - возможные ключи объединения.

2. Определи единицу анализа в зависимости от вопроса (см. SKILL.md «Единица анализа»):
   - товар;
   - товар и день;
   - товар и период;
   - отзыв;
   - категория;
   - складской остаток.

3. Все показатели по товарам рассчитывай ОТДЕЛЬНО для каждого товара.
   Нельзя применять показатель всего портфеля к отдельному товару,
   кроме случаев, когда портфель используется как явно обозначенный benchmark.

4. При объединении файлов:
   - нормализуй ключи через astype(str).str.strip();
   - проверь количество совпавших и несовпавших записей;
   - не объединяй по названию, если существует код или артикул;
   - не придумывай значения для несовпавших объектов.

5. Проверь все гипотезы из плана, но итоговый результат должен отвечать
   на исходный вопрос менеджера, а не просто перечислять статусы гипотез.

6. Если вопрос предполагает список объектов — ОБЯЗАТЕЛЬНО верни findings
   с конкретными товарами/отзывами. Одного count НЕДОСТАТОЧНО.

7. Для каждого finding верни:
   - entity_type (product / review / category);
   - entity_id (product_code или review_id);
   - name (название товара/категории);
   - priority (critical / high / medium / low — по классификации из SKILL.md);
   - reasons (массив конкретных причин с ЦИФРАМИ);
   - metrics (dict рассчитанных показателей);
   - recommended_action (конкретное действие менеджера).

8. Верни до 20 наиболее важных findings, отсортированных по приоритету:
   сначала critical, затем high, затем medium, затем low.
   Если найдено меньше 20 объектов — верни все.

9. В reasons используй конкретные значения.
   Плохо: "У товара снизились продажи."
   Хорошо: "Полученные заказы снизились со 190 до 120, падение 36.8%."

10. В recommended_action укажи конкретное действие менеджера.

11. Если необходимых данных нет:
    - не делай предположений;
    - установи answer_status="not_enough_data" или "partial";
    - перечисли отсутствующие данные в limitations;
    - объясни, какие данные необходимы для ответа.

12. График создавай ТОЛЬКО когда он помогает ответить на вопрос.
    График не обязателен для каждого skill.

## Формат результата

В конце обязательно выведи валидный JSON (через print(json.dumps(...))):

```python
result = {
    "answer_status": "answered",  # answered | partial | not_enough_data
    "answer": "Прямой ответ на вопрос менеджера в 1-3 предложениях",
    "findings": [
        {
            "entity_type": "product",
            "entity_id": "ЦБ-00007397",
            "name": "Название товара",
            "priority": "high",
            "reasons": ["Продажи снизились на 37%", "Доля отмен выросла с 4% до 12%"],
            "metrics": {"sales_current": 120, "sales_previous": 190, "change_pct": -36.8},
            "recommended_action": "Проверить остатки и цену"
        }
    ],
    "aggregates": {"total_checked": 3855, "problem_count": 14},
    "limitations": ["Нет данных по поставкам в пути"]
}
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
```

## Проверка перед выводом JSON

1. answer действительно отвечает на исходный вопрос.
2. Если вопрос просит товары или отзывы — findings НЕ пустой.
3. Каждый finding содержит entity_id и конкретные reasons с цифрами.
4. Портфельные показатели не выданы за показатели отдельного товара.
5. Отсутствующие данные явно указаны в limitations.
"""


# === Reference code: helpers/*.py для инжекции в CI prompt ===

HELPERS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "helpers")


def _load_helpers_code() -> str:
    """Загрузить исходный код helpers/*.py для инжекции в CI prompt.

    CI может переиспользовать проверенную логику вместо написания с нуля.
    """
    helper_files = ["sales.py", "stocks.py", "reviews.py"]
    blocks = []
    for name in helper_files:
        path = os.path.join(HELPERS_DIR, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
            blocks.append(f"### helpers/{name}\n```python\n{code}\n```")
    return "\n\n".join(blocks)


def _build_profile_block(manifest) -> str:
    """Render dataset profiles and semantic bindings for the prompt."""
    dataset_lines: list[str] = []
    for dataset in manifest.datasets:
        dataset_lines.append(f"### {dataset.dataset_id} — {dataset.logical_name}")
        for file_profile in dataset.files:
            dataset_lines.append(
                f"- file: {os.path.basename(file_profile.path)} | rows: {file_profile.row_count} | checksum: {file_profile.checksum}"
            )
            for column in file_profile.columns:
                dataset_lines.append(
                    f"  - column: {column.name} ({column.logical_type}), null_ratio={column.null_ratio:.2f}, unique={column.unique_count}"
                )
        for warning in dataset.warnings:
            dataset_lines.append(f"- warning: {warning}")

    binding_lines = [
        f"- {binding.concept} -> {binding.dataset_id}.{binding.column_name} (confidence={binding.confidence:.2f})"
        for binding in manifest.semantic_bindings
    ]

    return (
        "## Dataset profiles\n"
        + "\n".join(dataset_lines)
        + "\n\n## Semantic mapping\n"
        + ("\n".join(binding_lines) if binding_lines else "- no semantic bindings")
    )


# === Сборка prompt для Code Interpreter ===

def _build_prompt(plan: AnalysisPlan, balances_available: bool) -> str:
    """
    Собрать prompt для Code Interpreter.

    Универсальный формат результата (findings) + skill-специфичная методика (SKILL.md).
    Code Interpreter сам пишет и запускает Python код.
    """
    skill_md = _load_skill_md(plan.skill)
    helpers_code = _load_helpers_code()

    # Описание гипотез (опционально — CI проверяет, но результат в findings)
    hypotheses_text = []
    for h in plan.hypotheses:
        hypotheses_text.append(
            f"### {h.id}: {h.title}\n"
            f"- Датасеты: {', '.join(h.datasets)}\n"
            f"- Метод: {h.method}\n"
        )
    hypotheses_block = "\n".join(hypotheses_text)

    limitations_block = "\n".join(f"- {l}" for l in plan.limitations)

    stocks_note = ""
    if not balances_available:
        stocks_note = (
            "\n## ⚠️ 1С балансы НЕ загружены (VPN недоступен)\n"
            "Если анализ требует остатки — пометь answer_status=\"partial\", "
            "в limitations добавь «1С балансы недоступны (VPN)». "
            "НЕ ВЫДУМЫВАЙ остатки.\n"
        )

    product_codes_str = (
        ", ".join(plan.product_codes) if plan.product_codes
        else "не указаны (весь портфель)"
    )

    prompt = f"""# Анализ данных Mirrolla — ответь на вопрос менеджера

## Вопрос менеджера
**{plan.question}**

## Выбранный skill
{plan.skill.value}

## Период анализа
{plan.period.current_days} дней (comparison: {plan.period.comparison})

## Коды товаров
{product_codes_str}

## Инструкция skill (SKILL.md)
{skill_md}

## Reference code (helpers/*.py — проверенная логика, переиспользуй)
{helpers_code}

## Схема доступных данных
{DATA_SCHEMA}

## Гипотезы Planner (проверь, но результат в findings)
{hypotheses_block}

## Ограничения из Planner
{limitations_block}
{stocks_note}

## Файлы в sandbox
Файлы лежат в /mnt/data/ с именами вида `<file_id>-<original_name>`.
Сначала найди их:
```python
import os
files = os.listdir('/mnt/data/')
print(files)
```

{UNIVERSAL_ANALYSIS_INSTRUCTIONS}

## КРИТИЧЕСКИ ВАЖНО:
- **НЕ объясняй ход мыслей словами.** Сразу пиши Python код, выполняй его, и выводи JSON.
- **findings — обязательный массив конкретных объектов**, не счётчики.
- Используй default=str в json.dumps для numpy/pandas типов.
- Все тексты — на русском языке.
- Финальный ответ ОБЯЗАТЕЛЬНО содержит JSON с findings.
"""
    return prompt


def _build_manifest_prompt(plan: AnalysisPlan, manifest, balances_available: bool) -> str:
    """Prompt builder for the exemplar runtime."""
    skill_md = _load_skill_md(plan.skill)
    helpers_code = load_reference_code(HELPERS_DIR, plan)
    hypotheses_block = "\n".join(
        f"### {hypothesis.id}: {hypothesis.title}\n"
        f"- Datasets: {', '.join(hypothesis.datasets)}\n"
        f"- Method: {hypothesis.method}\n"
        for hypothesis in plan.hypotheses
    )
    limitations_block = "\n".join(f"- {limitation}" for limitation in manifest.limitations)
    restrictions_block = "\n".join(f"- {restriction}" for restriction in manifest.runtime_restrictions)
    stocks_note = ""
    if not balances_available:
        stocks_note = (
            "\n## Ограничение по остаткам\n"
            "- Датасет stocks не удалось подтвердить или он недоступен.\n"
            "- Если остатки нужны для вывода, верни limitation и partial/not_enough_data.\n"
        )

    return f"""# Mirrolla analytical execution manifest

## User question
{plan.question}

## Skill
- id: {manifest.skill_id}
- version: {manifest.skill_version}
- output_contract: {manifest.expected_output_contract}

## Requested scope
- product_codes: {', '.join(plan.product_codes) if plan.product_codes else 'all products'}
- current_period_days: {manifest.current_period_days}
- comparison_method: {manifest.comparison_method}

{_build_profile_block(manifest)}

## Hypotheses approved by planner
{hypotheses_block}

## Planner limitations
{limitations_block or '- none'}
{stocks_note}

## Runtime restrictions
{restrictions_block}

## Skill methodology
{skill_md}

## Relevant reference code
{helpers_code or _load_helpers_code()}

{UNIVERSAL_ANALYSIS_INSTRUCTIONS}

## Critical rules
- Use only datasets and columns explicitly listed in dataset profiles and semantic mapping.
- If a required concept is unavailable, do not guess. Return `partial` or `not_enough_data`.
- Keep `change_pct` null when previous period is zero. Do not emit NaN or inf.
- Final output must be valid JSON with keys: answer_status, answer, findings, limitations.
- Every finding for this skill must describe a concrete product and include `metrics.change_pct`.
"""


# === Парсинг результатов Code Interpreter ===

def _extract_json_from_text(text: str) -> dict | None:
    """
    Извлечь JSON результата из текстового ответа Assistant.

    Code Interpreter обычно выводит результат в stdout (виден в text block),
    иногда в markdown ```python блоке.
    """
    if not text:
        return None

    # Попытка 1: JSON в markdown блоке (```python, ```json, или просто ```)
    patterns = [
        r'```python\s*\n(.*?)```',
        r'```json\s*\n(.*?)```',
        r'```\s*\n(.*?)```',
        r'(result\s*=\s*\{.*?\})\s*\n\s*print',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for m in matches:
            try:
                if m.strip().startswith("result"):
                    m = m.split("=", 1)[1].strip()
                # Remove JS-style comments (// ...) on their own line — LLM sometimes adds them
                m_clean = re.sub(r'^\s*//.*$', '', m, flags=re.MULTILINE)
                return json.loads(m_clean)
            except json.JSONDecodeError:
                continue

    # Попытка 2: найти первый валидный JSON с findings или hypothesis_results
    try:
        for key in ("findings", "hypothesis_results"):
            idx = text.find(f'"{key}"')
            if idx == -1:
                continue
            # Найти начало JSON (открытие {)
            start = text.rfind("{", 0, idx)
            if start == -1:
                continue
            # Найти конец JSON (баланс скобок)
            depth = 0
            for i, ch in enumerate(text[start:], start=start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        # Remove JS-style comments before parsing
                        candidate_clean = re.sub(r'^\s*//.*$', '', candidate, flags=re.MULTILINE)
                        return json.loads(candidate_clean)
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _parse_ci_result(
    ci_result: dict, plan: AnalysisPlan
) -> tuple[list[Finding], list[HypothesisResult], str, str, list[str]]:
    """
    Разобрать результат Code Interpreter.

    Args:
        ci_result: {status, text, charts, error} from CIRunner.
        plan: исходный план.

    Returns:
        (findings, hypothesis_results, answer_status, answer, extra_limitations)
    """
    findings: list[Finding] = []
    hypothesis_results: list[HypothesisResult] = []
    answer_status = "answered"
    answer = ""
    extra_limitations: list[str] = []

    if not ci_result.get("text"):
        return findings, hypothesis_results, answer_status, answer, extra_limitations

    text = ci_result["text"]
    parsed = _extract_json_from_text(text)

    if not parsed:
        # JSON не найден — возвращаем текст как answer
        answer = text[:1000] if text else "Code Interpreter не вернул результат"
        answer_status = "partial"
        extra_limitations.append("Не удалось распарсить JSON из ответа CI")
        return findings, hypothesis_results, answer_status, answer, extra_limitations

    # answer_status и answer (основной формат)
    answer_status = parsed.get("answer_status", "answered")
    answer = parsed.get("answer", "")

    # findings — основной результат
    for f in parsed.get("findings", []):
        try:
            # Sanitize metrics: NaN → None (not JSON-serializable, not useful)
            raw_metrics = f.get("metrics", {})
            if isinstance(raw_metrics, dict):
                clean_metrics = {}
                for k, v in raw_metrics.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        clean_metrics[k] = None
                    else:
                        clean_metrics[k] = v
            else:
                clean_metrics = {}

            # Sanitize reasons: replace "nan" mentions
            clean_reasons = []
            for r in f.get("reasons", []):
                if isinstance(r, str):
                    # "запас на nan дня" → "запас на N/A"
                    r_clean = r.replace("nan", "N/A")
                    clean_reasons.append(r_clean)
                else:
                    clean_reasons.append(str(r))

            findings.append(Finding(
                entity_type=f.get("entity_type", "product"),
                entity_id=str(f.get("entity_id") or "?"),
                name=f.get("name", "?"),
                priority=f.get("priority", "medium"),
                reasons=clean_reasons,
                metrics=clean_metrics,
                recommended_action=f.get("recommended_action", ""),
            ))
        except Exception as e:
            print(f"  [Executor] ⚠ Ошибка парсинга finding {f.get('entity_id', '?')}: {e}")

    # hypothesis_results — опционально (старый формат, CI может вернуть)
    for hr in parsed.get("hypothesis_results", []):
        try:
            data = hr.get("data")
            if isinstance(data, str):
                data = {"raw": data}
            hypothesis_results.append(HypothesisResult(
                hypothesis_id=hr.get("hypothesis_id", "?"),
                title=hr.get("title", "?"),
                confirmed=hr.get("confirmed"),
                detail=hr.get("detail", ""),
                data=data if isinstance(data, dict) else ({"raw": str(data)} if data else None),
            ))
        except Exception as e:
            print(f"  [Executor] ⚠ Ошибка парсинга гипотезы {hr.get('hypothesis_id', '?')}: {e}")

    extra_lim = parsed.get("limitations", [])
    if extra_lim:
        extra_limitations.extend(extra_lim)

    return findings, hypothesis_results, answer_status, answer, extra_limitations


# === Семантическая валидация результата ===

# Skills, где ответ должен быть списком конкретных объектов (не только анализ)
LIST_RESULT_SKILLS = {
    "inventory-planning",
    "portfolio-growth",
    "reviews-and-pricing",
}


def validate_analysis_result(
    parsed: dict,
    skill: str,
) -> list[str]:
    """
    Семантическая проверка результата CI.

    Возвращает список ошибок. Если пустой — результат валиден.
    """
    errors = []

    if not parsed:
        errors.append("Результат пустой (нет JSON)")
        return errors

    # answer должен быть
    if not parsed.get("answer"):
        errors.append("Отсутствует прямой ответ в поле answer")

    # Для list-вопросов findings не должен быть пустым
    if skill in LIST_RESULT_SKILLS:
        findings = parsed.get("findings", [])
        if not findings:
            errors.append(
                f"Вопрос требует список конкретных объектов (skill={skill}), "
                "но findings пустой"
            )

    # Каждый finding должен иметь entity_id и reasons
    for i, f in enumerate(parsed.get("findings", [])):
        if not f.get("entity_id"):
            errors.append(f"findings[{i}]: отсутствует entity_id")

    return errors


# === Главный execute() ===

def _execute_legacy(plan: AnalysisPlan, max_retries: int = 2) -> ExecutionResult:
    """
    Выполнить план анализа через OpenAI Code Interpreter.

    Args:
        plan: план анализа от Planner.
        max_retries: максимум попыток повторного запроса к CI (если невалидный JSON).

    Returns:
        ExecutionResult: результаты + графики.
    """
    print(f"\n{'='*60}")
    print(f"  EXECUTOR — OpenAI Code Interpreter")
    print(f"{'='*60}")

    # Шаг 1: Pre-fetch балансов (если нужны)
    print("\n  [Executor] Шаг 1: Проверка 1С балансов...")
    balances_ok, balances_msg = _prefetch_balances(plan)
    print(f"  [Executor] Балансы: {balances_msg}")

    # Шаг 2: Сбор файлов для загрузки
    print("\n  [Executor] Шаг 2: Сбор файлов данных...")
    file_paths = _collect_data_files(plan)
    print(f"  [Executor] Файлов к загрузке: {len(file_paths)}")
    for fp in file_paths:
        print(f"    → {os.path.basename(fp)} ({os.path.getsize(fp) // 1024} KB)")

    # Шаг 3: Сборка prompt
    print("\n  [Executor] Шаг 3: Сборка prompt...")
    prompt = _build_prompt(plan, balances_ok)
    print(f"  [Executor] Prompt: {len(prompt)} символов")

    # Шаг 4: Запуск Code Interpreter (self-correction встроен в ci_runner)
    from agent.ci_runner import CIRunner

    errors = []
    limitations = list(plan.limitations)
    charts = []

    runner = CIRunner()
    try:
        ci_result = runner.run_analysis(
            prompt=prompt,
            file_paths=file_paths,
            max_retries=2,  # self-correction через previous_response_id
        )
    except Exception as e:
        print(f"  [Executor] ❌ CI ошибка: {e}")
        ci_result = {"status": "failed", "error": str(e), "text": "", "charts": []}
        errors.append(f"CI error: {e}")

    if ci_result.get("error"):
        errors.append(ci_result["error"])

    print(f"  [Executor] ✅ CI выполнен (status={ci_result.get('status')})")

    # Шаг 5: Парсинг результатов
    print("\n  [Executor] Шаг 5: Парсинг результатов...")
    findings, hypothesis_results, answer_status, answer, extra_lim = _parse_ci_result(ci_result, plan)
    charts = ci_result.get("charts", [])

    # Семантическая валидация (Шаг 4)
    print("\n  [Executor] Шаг 5b: Валидация результата...")
    parsed_for_validation = _extract_json_from_text(ci_result.get("text", ""))
    validation_errors = validate_analysis_result(parsed_for_validation or {}, plan.skill.value)
    if validation_errors:
        print(f"  [Executor] ⚠ Валидация: {len(validation_errors)} ошибок")
        for ve in validation_errors:
            print(f"     - {ve}")
        # Если findings пустой для list-вопроса — retry через ci_runner self-correction
        if not findings and plan.skill.value in LIST_RESULT_SKILLS and not ci_result.get("_validated_retry"):
            print(f"  [Executor] → retry с указанием ошибок валидации...")
            correction = (
                f"Результат не прошёл валидацию:\n{json.dumps(validation_errors, ensure_ascii=False)}\n"
                "Исправь: верни findings с конкретными товарами (entity_id, reasons, metrics). "
                "Не возвращай пустой findings."
            )
            # Дополнительный retry через предыдущий run
            try:
                runner2 = CIRunner()
                ci_result2 = runner2.run_analysis(
                    prompt=prompt + f"\n\n## ⚠️ ВАЛИДАЦИЯ ПРЕДЫДУЩЕЙ ПОПЫТКИ:\n{correction}",
                    file_paths=file_paths,
                    max_retries=1,
                )
                if ci_result2.get("text"):
                    findings2, hyps2, status2, answer2, lims2 = _parse_ci_result(ci_result2, plan)
                    if findings2:
                        print(f"  [Executor] ✅ Retry дал {len(findings2)} findings")
                        findings = findings2
                        hypothesis_results = hyps2
                        answer_status = status2
                        answer = answer2
                        if lims2:
                            extra_lim = lims2
                        charts = ci_result2.get("charts", [])
            except Exception as retry_err:
                print(f"  [Executor] ⚠ Retry failed: {retry_err}")
    else:
        print(f"  [Executor] ✅ Валидация пройдена")
    if extra_lim:
        limitations.extend(extra_lim)

    print(f"  [Executor] ✅ Findings: {len(findings)}")
    print(f"  [Executor] ✅ Гипотез: {len(hypothesis_results)}")
    print(f"  [Executor] ✅ answer_status: {answer_status}")
    print(f"  [Executor] 📊 Графиков: {len(charts)}")

    # Если 1С был недоступен — добавить limitation
    if not balances_ok and any("stocks" in h.datasets for h in plan.hypotheses):
        limitations.append("1С балансы недоступны (VPN) — гипотезы по остаткам не проверены")

    # Шаг 6: Reporter LLM — интерпретация findings в ответ менеджеру
    print("\n  [Executor] Шаг 6: Reporter LLM...")
    try:
        from agent.reporter import synthesize as reporter_synthesize
        manager_answer = reporter_synthesize(
            question=plan.question,
            skill=plan.skill,
            findings=findings,
            limitations=limitations,
            answer_status=answer_status,
            ci_answer=answer,
        )
        print(f"  [Executor] ✅ Reporter: {len(manager_answer)} символов")
    except Exception as e:
        print(f"  [Executor] ⚠ Reporter error: {e}")
        manager_answer = answer  # fallback на CI answer

    result = ExecutionResult(
        question=plan.question,
        skill=plan.skill,
        answer_status=answer_status,
        findings=findings,
        hypothesis_results=hypothesis_results,
        charts=charts,
        summary=manager_answer,  # ответ от Reporter LLM (не CI answer)
        limitations=limitations,
        code_generated=None,
        errors=errors,
    )

    print(f"\n  [Executor] === Итог ===")
    print(f"  Findings: {len(findings)}")
    print(f"  Гипотез проверено: {len(hypothesis_results)}")
    print(f"  Графиков: {len(charts)}")
    print(f"  Ошибок: {len(errors)}")

    return result


def _execute_exemplar(plan: AnalysisPlan, max_retries: int = 2) -> ExecutionResult:
    """Execute the sales-decline exemplar via manifest/profile/mapping contracts."""
    from agent.runtime.manifest_builder import build_manifest
    from agent.runtime.profiler import profile_datasets
    from agent.runtime.reference_loader import load_reference_code
    from agent.runtime.semantic_mapper import build_semantic_mapping
    from agent.runtime.skill_loader import load_skill_metadata
    from agent.runtime.validation import (
        validate_generic_result,
        validate_sales_decline_result,
    )

    print(f"\n{'='*60}")
    print("  EXECUTOR — Exemplar Runtime")
    print(f"{'='*60}")

    print("\n  [Executor] Шаг 1: Pre-fetch и профилирование данных...")
    balances_ok, balances_msg = _prefetch_balances(plan)
    print(f"  [Executor] Балансы: {balances_msg}")

    dataset_ids = sorted({
        dataset
        for hypothesis in plan.hypotheses
        for dataset in hypothesis.datasets
    })
    profiles = profile_datasets(PROJECT_ROOT, dataset_ids)
    metadata = load_skill_metadata(plan.skill)
    bindings, missing_required = build_semantic_mapping(profiles, metadata)
    limitations = list(plan.limitations)
    if missing_required:
        limitations.append(
            "Отсутствуют обязательные бизнес-концепты: " + ", ".join(sorted(missing_required))
        )
        return ExecutionResult(
            question=plan.question,
            skill=plan.skill,
            answer_status="not_enough_data",
            findings=[],
            hypothesis_results=[],
            charts=[],
            summary="Недостаточно данных для достоверного анализа.",
            limitations=limitations,
            code_generated=None,
            errors=[],
        )

    manifest = build_manifest(plan, metadata, profiles, bindings)
    prompt = _build_manifest_prompt(plan, manifest, balances_ok)
    file_paths = _collect_data_files(plan)
    errors: list[str] = []

    print("\n  [Executor] Шаг 2: Запуск Code Interpreter...")
    from agent.ci_runner import CIRunner

    runner = CIRunner()
    try:
        ci_result = runner.run_analysis(
            prompt=prompt,
            file_paths=file_paths,
            max_retries=max_retries,
        )
    except Exception as e:
        errors.append(f"CI error: {e}")
        ci_result = {"status": "failed", "text": "", "charts": [], "error": str(e)}

    findings, hypothesis_results, answer_status, answer, extra_lim = _parse_ci_result(ci_result, plan)
    limitations.extend(extra_lim)

    parsed = _extract_json_from_text(ci_result.get("text", "")) or {}
    generic_report = validate_generic_result(parsed, manifest)
    sales_report = validate_sales_decline_result(parsed, manifest)

    validation_errors = [issue.message for issue in generic_report.issues + sales_report.issues]
    if validation_errors:
        print(f"  [Executor] ⚠ Validator issues: {len(validation_errors)}")
        for issue in validation_errors:
            print(f"     - {issue}")
        if len(errors) < max_retries:
            limitations.append("Validation issues: " + "; ".join(validation_errors))
        if not findings and answer_status == "answered":
            answer_status = "partial"
    else:
        print("  [Executor] ✅ Validators passed")

    if not balances_ok and "stocks" in dataset_ids:
        limitations.append("1С балансы недоступны (VPN) — гипотезы по остаткам не проверены")

    print("\n  [Executor] Шаг 3: Reporter...")
    try:
        from agent.reporter import synthesize as reporter_synthesize
        manager_answer = reporter_synthesize(
            question=plan.question,
            skill=plan.skill,
            findings=findings,
            limitations=limitations,
            answer_status=answer_status,
            ci_answer=answer,
        )
    except Exception as e:
        manager_answer = answer
        errors.append(f"Reporter error: {e}")

    return ExecutionResult(
        question=plan.question,
        skill=plan.skill,
        answer_status=answer_status,
        findings=findings,
        hypothesis_results=hypothesis_results,
        charts=ci_result.get("charts", []),
        summary=manager_answer,
        limitations=limitations,
        code_generated=None,
        errors=errors,
    )


def _build_attached_profile_block(execution_manifest: ExecutionManifest) -> str:
    lines = [
        "## Attached datasets for this analysis",
        "Use only these files and only these profiled columns.",
        "Do not assume any global demo files, schemas, or hidden columns.",
    ]
    for dataset in execution_manifest.datasets:
        lines.append(
            f"### {dataset.sandbox_filename} | dataset_version_id={dataset.dataset_version_id} | display_name={dataset.display_name} | format={dataset.format}"
        )
        for sheet in dataset.profile.sheets:
            lines.append(
                f"- sheet: {sheet.name} | row_count={sheet.row_count} | sampled={sheet.sampled}"
            )
            for warning in sheet.warnings:
                lines.append(f"  - warning: {warning}")
            for column in sheet.columns:
                parts = [
                    f"  - column: {column.name}",
                    f"type={column.inferred_type}",
                    f"null_ratio={column.null_ratio:.3f}",
                ]
                if column.unique_count is not None:
                    parts.append(f"unique={column.unique_count}")
                if column.min_value is not None:
                    parts.append(f"min={column.min_value}")
                if column.max_value is not None:
                    parts.append(f"max={column.max_value}")
                if column.examples:
                    parts.append(f"examples={', '.join(column.examples)}")
                lines.append(" | ".join(parts))
        for warning in dataset.profile.warnings:
            lines.append(f"- profile_warning: {warning}")
    return "\n".join(lines)


def _build_attached_prompt(
    plan: AnalysisPlan,
    execution_manifest: ExecutionManifest,
) -> str:
    skill_md = _load_skill_md(plan.skill)
    helpers_code = _load_helpers_code()
    hypotheses_text = []
    for hypothesis in plan.hypotheses:
        hypotheses_text.append(
            f"### {hypothesis.id}: {hypothesis.title}\n"
            f"- Datasets: {', '.join(hypothesis.datasets)}\n"
            f"- Method: {hypothesis.method}\n"
        )
    return (
        f"{UNIVERSAL_ANALYSIS_INSTRUCTIONS}\n\n"
        f"## Skill\n{plan.skill.value}\n\n"
        f"## Question\n{plan.question}\n\n"
        f"## Skill instructions\n{skill_md}\n\n"
        f"## Attached execution manifest\n"
        f"analysis_id={execution_manifest.analysis_id}\n"
        f"manifest_version={execution_manifest.manifest_version}\n\n"
        f"{_build_attached_profile_block(execution_manifest)}\n\n"
        f"## Hypotheses to validate\n{''.join(hypotheses_text)}\n"
        f"## Reference helpers\n{helpers_code}\n"
    )


def _build_execution_metadata(
    execution_manifest: ExecutionManifest | None,
    analysis_id: str | None,
) -> ExecutionMetadata | None:
    if execution_manifest is None:
        return None
    return ExecutionMetadata(
        manifest_version=execution_manifest.manifest_version,
        analysis_id=analysis_id,
        datasets=[
            ExecutionDatasetMetadata(
                dataset_id=item.dataset_id,
                dataset_version_id=item.dataset_version_id,
                original_filename=item.original_filename,
                format=item.format,
                checksum_sha256=item.checksum_sha256,
            )
            for item in execution_manifest.datasets
        ],
    )


def _execute_attached(
    plan: AnalysisPlan,
    *,
    analysis_id: str | None,
    execution_manifest: ExecutionManifest,
    file_paths: list[str],
    max_retries: int = 2,
) -> ExecutionResult:
    from agent.ci_runner import CIRunner

    prompt = _build_attached_prompt(plan, execution_manifest)
    runner = CIRunner()
    errors: list[str] = []
    limitations = list(plan.limitations)
    execution_metadata = _build_execution_metadata(execution_manifest, analysis_id)
    ci_result = runner.run_analysis(
        prompt=prompt,
        file_paths=file_paths,
        max_retries=max_retries,
    )
    if ci_result.get("error"):
        errors.append(ci_result["error"])

    findings, hypothesis_results, answer_status, answer, extra_lim = _parse_ci_result(ci_result, plan)
    limitations.extend(extra_lim)

    try:
        from agent.reporter import synthesize as reporter_synthesize

        manager_answer = reporter_synthesize(
            question=plan.question,
            skill=plan.skill,
            findings=findings,
            limitations=limitations,
            answer_status=answer_status,
            ci_answer=answer,
        )
    except Exception as exc:
        manager_answer = answer
        errors.append(f"Reporter error: {exc}")

    return ExecutionResult(
        question=plan.question,
        skill=plan.skill,
        answer_status=answer_status,
        findings=findings,
        hypothesis_results=hypothesis_results,
        charts=ci_result.get("charts", []),
        summary=manager_answer,
        limitations=limitations,
        code_generated=None,
        errors=errors,
        execution_metadata=execution_metadata,
    )


def execute(
    plan: AnalysisPlan,
    *,
    analysis_id: str | None = None,
    execution_manifest: ExecutionManifest | None = None,
    file_paths: list[str] | None = None,
    max_retries: int = 2,
) -> ExecutionResult:
    if execution_manifest is not None:
        return _execute_attached(
            plan,
            analysis_id=analysis_id,
            execution_manifest=execution_manifest,
            file_paths=list(file_paths or []),
            max_retries=max_retries,
        )
    return _execute_legacy(plan, max_retries=max_retries)


# === CLI ===

def main():
    if len(sys.argv) < 2:
        print("Использование: python -m agent.executor \"Вопрос менеджера\"")
        print()
        print("Примеры:")
        print('  python -m agent.executor "Почему упали продажи ЦБ-00007397?"')
        print('  python -m agent.executor "Что заканчивается на складе?"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"Вопрос: {question}")

    # Шаг 1: Plan
    print("\n--- Шаг 1: Planner ---")
    analysis_plan = generate_plan(question)
    print(f"Skill: {analysis_plan.skill.value}")
    print(f"Гипотез: {len(analysis_plan.hypotheses)}")

    # Шаг 2: Execute
    print("\n--- Шаг 2: Executor ---")
    result = execute(analysis_plan)

    # Шаг 3: Вывод
    print(f"\n{'='*60}")
    print(f"  РЕЗУЛЬТАТ АНАЛИЗА")
    print(f"{'='*60}")

    print(f"\n📋 Вопрос: {result.question}")
    print(f"🎯 Skill: {result.skill.value}")
    print(f"📊 answer_status: {result.answer_status}")

    if result.findings:
        print(f"\n🔎 Findings ({len(result.findings)}):")
        for f in result.findings:
            priority_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(f.priority, "⚪")
            print(f"  {priority_icon} [{f.priority}] {f.entity_id} — {f.name}")
            for r in f.reasons:
                print(f"       • {r}")
            if f.metrics:
                print(f"       metrics: {json.dumps(f.metrics, ensure_ascii=False, default=str)[:200]}")
            if f.recommended_action:
                print(f"       → {f.recommended_action}")

    if result.hypothesis_results:
        print(f"\n📊 Гипотезы:")
        for hr in result.hypothesis_results:
            status = "✅" if hr.confirmed is True else ("❌" if hr.confirmed is False else "❓")
            print(f"  {status} {hr.hypothesis_id}: {hr.title}")
            print(f"     {hr.detail[:200]}")
            if hr.data:
                print(f"     Данные: {json.dumps(hr.data, ensure_ascii=False, default=str)[:300]}")

    if result.charts:
        print(f"\n📊 Графики:")
        for c in result.charts:
            print(f"  → {c}")

    if result.summary:
        print(f"\n📝 Итог:")
        print(f"  {result.summary[:800]}")

    if result.limitations:
        print(f"\n⚠ Ограничения:")
        for l in result.limitations:
            print(f"  - {l}")

    if result.errors:
        print(f"\n❌ Ошибки:")
        for e in result.errors:
            print(f"  - {e[:300]}")

    # JSON вывод
    print(f"\n--- JSON ---")
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
