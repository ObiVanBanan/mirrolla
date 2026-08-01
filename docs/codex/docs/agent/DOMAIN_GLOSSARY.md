# Доменный словарь

## Skill

Версионируемый пакет аналитической методики. Определяет смысл анализа, concepts, hypotheses, formulas, limitations, reference code, output contract и validator.

## Business concept

Стабильное доменное понятие, не привязанное к имени колонки. Примеры: `product_identifier`, `order_date`, `stock_balance`, `review_text`.

## Data workspace

Пользовательский контейнер логических datasets и их versions. На первом этапе может существовать один default workspace.

## Dataset

Логический источник данных, например «Продажи Ozon». Может иметь несколько immutable versions.

## Dataset source

Логический источник данных из registry: например Ozon orders, WB reviews, 1С catalog или balances.

## Dataset version

Конкретный immutable uploaded/system snapshot источника с id, checksum, storage key, status, временем импорта, format/sheet и profile. Это identity, которую сохраняет analysis.

## Raw file storage

Boundary для потокового хранения исходных файлов. Клиент не управляет physical path; application layer работает со storage key.

## Dataset profile

Безопасное структурированное описание фактического файла: поля, типы, ranges, nulls, examples и warnings. Не содержит полный DataFrame.

## Semantic mapping

Связь business concept с `dataset_id + physical column`, confidence и evidence.

## Analysis dataset selection

Упорядоченный список exact DatasetVersion ids, закреплённый за analysis до исполнения.

## Analysis plan

Согласуемая с менеджером методика конкретного ответа: hypotheses, periods, datasets и limitations. Не является кодом.

## Execution manifest

Полный воспроизводимый контракт запуска, зафиксированный до генерации кода.

## Reference code

Проверенный пример реализации бизнес-методики. Модель может адаптировать техническую реализацию, но не менять смысл молча.

## Generated code

Python-код, написанный моделью для конкретного manifest и выполненный в Code Interpreter.

## Finding

Один проверенный аналитический вывод об entity с priority, reasons и metrics.

## Aggregate

Проверенная метрика уровня портфеля, категории или периода. Не должна маскироваться под метрику отдельного товара.

## Limitation

Явное описание того, какой вывод нельзя сделать или почему результат частичный.

## Validation issue

Machine-readable ошибка или warning с code, severity, message и path.

## Repair

Повторное выполнение в том же аналитическом контексте с задачей исправить конкретные validation issues, не меняя утверждённый план.

## Reporter

Слой представления validated result менеджеру. Не аналитический движок.

## Exemplar

Первый полный vertical slice нового паттерна. Для текущей миграции — `sales-decline-analysis`.
