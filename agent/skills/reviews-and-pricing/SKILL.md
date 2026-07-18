# Skill: reviews-and-pricing

## Назначение
Анализ отзывов, выявление негатива, повторяющихся жалоб и кандидатов на изменение цены.

## Доступные датасеты
- **reviews_wb** — WB отзывы (4132 отзыва, 270 товаров)
  - Колонки: review_id, date, product_code, article_wb, rating, brand, text, pros, cons, region, format, barcode, ...
- **reviews_ozon** — Ozon отзывы (внутри датасета sales, где review_text не пустой)
- **sales** — Ozon orders (для контекста продаж)
  - Колонки: product_code, date, rating, review_text, order_status, ...
- **categories** — 1С productType
  - Колонки: product_code, catalog_name, product_type, brand, gtin, articleOzon, articleWb

## Гипотезы по умолчанию

### H1: Негативные отзывы WB (1-2★)
- **Датасеты:** reviews_wb
- **Метод:** Фильтр rating <= 2, сортировка по дате. Показать последние негативные отзывы.
- **Helpers:** `load_wb_reviews`, `negative_reviews_wb`

### H2: Негативные отзывы Ozon (1-2★)
- **Датасеты:** reviews_ozon (sales)
- **Метод:** Фильтр rating <= 2, выборка с текстом отзыва.
- **Helpers:** `load_ozon`, `negative_reviews_ozon`

### H3: Повторяющиеся жалобы
- **Датасеты:** reviews_wb
- **Метод:** Группировать негативные отзывы по product_code, найти товары с множественными жалобами на одну тему.
- **Helpers:** `load_wb_reviews`, `recurring_complaints`

### H4: Товары, требующие ответа
- **Датасеты:** reviews_wb
- **Метод:** Найти отзывы без ответа продавца (колонка "Ответ" = NaN в WB). Указать, что продавец не отвечал ни на один отзыв.
- **Helpers:** `load_wb_reviews`, `reviews_requiring_response`

### H5: Кандидаты на изменение цены
- **Датасеты:** reviews_wb, reviews_ozon, sales
- **Метод:** Товары с высоким числом негативных отзывов + стабильным спросом → кандидаты на снижение цены. Товары с высокими оценками + растущим спросом → кандидаты на повышение.
- **Helpers:** `review_summary`, `compare_periods`, `negative_reviews_wb`
- **⚠️ ОГРАНИЧЕНИЕ:** Нет цены продажи и цен конкурентов — рекомендация только качественная ("рассмотреть снижение/повышение/сохранить").

## Ограничения
- Нет цены продажи — нельзя рассчитать оптимальную цену
- Нет цен конкурентов — нельзя сравнить
- Нет себестоимости, комиссий, рекламных расходов
- "Ответ" продавца в WB = все NaN (продавец не отвечает на отзывы)
- ~80% отзывов Ozon без текста (только оценка)
- Нет данных о возвратах

## Единица анализа
Отзыв (для вопроса «какие отзывы требуют реакции») или товар (для повторяющихся жалоб).

## Метрики (для каждого отзыва)
- review_id — ID отзыва
- product_code — артикул товара
- product_name — название товара
- rating — оценка (1-5)
- review_text — текст отзыва (если есть; иначе pros/cons)
- date — дата отзыва
- has_response — есть ли ответ продавца (WB: все false — продавец не отвечает)

## Метрики (для каждого товара — повторяющиеся жалобы)
- product_code
- negative_count — количество негативных отзывов (1-2★)
- avg_rating — средняя оценка
- recurring_themes — повторяющиеся темы жалоб (по тексту)

## ВАЖНО по обработке данных:
1. WB отзывы: лист "feedbacks", колонка "Артикул продавца" == product_code.
2. Ozon отзывы: внутри Ozon sales, где "Текст отзыва" не пустой, колонка "Оценка".
3. Текст отзыва: если "Текст отзыва" пустой — взять "Достоинства" + "Недостатки" (WB).
4. Дата: WB колонка "Дата", Ozon колонка "Дата публикации".
5. Для Ozon: rating = колонка "Оценка".
6. Выводи ВСЕ findings (до 20) полностью, без `//` комментариев, без `...` сокращений.

## Классификация priority (для отзывов)
- rating == 1, жалоба на вред здоровью/брак/протечка/аллергия → **critical**
- rating == 2, повторяющаяся проблема, отзыв без ответа → **high**
- rating == 3, негативный текст → **medium**
- rating >= 4 → не попадает в findings (позитив)

## findings (обязательный формат результата)
Для вопроса «какие отзывы требуют реакции» — топ-N негативных отзывов:
- entity_type: "review"
- entity_id: review_id (или product_code если review_id нет)
- name: product_name (название товара, не текст отзыва)
- priority: critical / high / medium
- reasons: ["Оценка 1★", "Жалоба на брак: 'тюбик протекает'", "Продавец не ответил"]
- metrics: {rating, date, product_code, has_response}
- recommended_action: "Ответить клиенту", "Проверить партию на брак"

Для повторяющихся жалоб (группировка по товару):
- entity_type: "product"
- entity_id: product_code
- reasons: ["5 негативных отзывов на тему 'аллергия'", "Средний рейтинг 2.1"]
- recommended_action: "Проверить состав", "Связаться с производством"

## Подходящий график
Количество отзывов по оценкам (1-5★) — bar chart.

## Helper reference (файлы с реальным кодом)
Executor читает эти файлы и передаёт их исходник в LLM prompt:

- **helpers/reviews.py** — функции: `load_wb_reviews`, `normalize_wb_reviews`, `negative_reviews_wb`, `negative_reviews_ozon`, `review_summary`, `reviews_requiring_response`, `recurring_complaints`
- **helpers/sales.py** — функции: `load_ozon` (для контекста продаж)