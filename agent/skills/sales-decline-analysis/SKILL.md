# Skill: sales-decline-analysis

## Назначение
Анализ причин падения продаж конкретного товара или группы товаров.

## Доступные датасеты
- **sales** — Ozon orders по дням (170K строк, 351 товар, период 17.03–16.06.2026)
  - Колонки: product_code, sku_ozon, product_name, order_id, order_status, review_text, date, review_status, rating, photo_count, video_count, reply_count
- **stocks** — 1С ProductBalances (текущий snapshot остатков)
  - Колонки: product_code, name, balance
- **reviews_wb** — WB отзывы (4132 отзыва, 270 товаров)
  - Колонки: review_id, date, product_code, article_wb, rating, brand, text, pros, cons, region, ...
- **reviews_ozon** — Ozon отзывы (внутри датасета sales, где review_text не пустой)
- **categories** — 1С productType (категория товара: Косметика, БАД, и т.д.)
  - Колонки: product_code, catalog_name, product_type, brand, gtin, articleOzon, articleWb

## Гипотезы-кандидаты (Planner выбирает релевантные под период)

### Короткий период (1-7 дней) — операционные причины
**H: Out-of-stock / технический сбой**
- **Датасеты:** sales, stocks
- **Метод:** Проверить резко ли упали продажи (к ~0), сравнить с остатками
- **Helpers:** `compare_periods`, `stockout_days`, `out_of_stock`
- **Когда выбирать:** period ≤ 7 дней, фокус на операционных причинах

**H: Резкий негативный всплеск**
- **Датасеты:** reviews_wb
- **Метод:** Проверить всплеск негативных отзывов в последние дни
- **Helpers:** `negative_reviews_wb`, `reviews_requiring_response`
- **Когда выбирать:** period ≤ 7 дней

### Средний период (14-30 дней) — сбалансированный анализ
**H: Дефицит остатков**
- **Датасеты:** sales, stocks
- **Метод:** Сопоставить продажи с остатками. Out-of-stock если продажи упали при критических остатках
- **Helpers:** `compare_periods`, `stockout_days`, `critical_stocks`, `out_of_stock`
- **Когда выбирать:** period 14-30 дней

**H: Рост негативных отзывов**
- **Датасеты:** reviews_wb, reviews_ozon
- **Метод:** Сравнить средний рейтинг и долю негативных отзывов текущего и предыдущего периода
- **Helpers:** `negative_reviews_wb`, `negative_reviews_ozon`, `review_summary`
- **Когда выбирать:** period ≥ 14 дней

**H: Динамика категории**
- **Датасеты:** sales, categories
- **Метод:** Сравнить продажи товара с его категорией. Если категория тоже упала — проблема рыночная
- **Helpers:** `category_growth_by_type`, `faster_than_market`, `load_product_categories`
- **Когда выбирать:** period ≥ 14 дней

**H: Сезонность / тренд**
- **Датасеты:** sales
- **Метод:** Тренд заказов по дням. Падение может быть сезонным
- **Helpers:** `daily_order_counts`, `compare_periods`, `category_growth`
- **Когда выбирать:** period ≥ 14 дней, умеренная релевантность

### Длинный период (60+ дней) — стратегические причины
**H: Долгосрочный тренд / сезонность**
- **Датасеты:** sales
- **Метод:** Анализ тренда за весь период, выявление сезонных паттернов
- **Helpers:** `daily_order_counts`, `compare_periods`, `category_growth`
- **Когда выбирать:** period ≥ 60 дней, ВЫСОКИЙ приоритет

**H: Накопленные негативные отзывы**
- **Датасеты:** reviews_wb, reviews_ozon
- **Метод:** Оценить накопленный негатив за весь период, не просто сравнение периодов
- **Helpers:** `review_summary`, `recurring_complaints`, `negative_reviews_wb`
- **Когда выбирать:** period ≥ 60 дней

**H: Хронический дефицит остатков**
- **Датасеты:** sales, stocks
- **Метод:** Проверить системные проблемы с поставками
- **Helpers:** `stockout_days`, `critical_stocks`, `production_plan`
- **Когда выбирать:** period ≥ 60 дней

### Непроверяемые гипотезы (всегда → limitations)
**H: Изменение цены**
- ⚠️ Нет колонки цены в данных. Всегда в limitations.

**H: Реклама, SEO, конкуренты**
- ⚠️ Нет данных. Всегда в limitations.

## Ограничения (обязательно указать в плане)
- Нет цены продажи — H2 не проверяем
- Нет цен конкурентов
- Нет данных о рекламе (рекламные кампании, показатели, расходы)
- Нет поисковых позиций (SEO, ранжирование)
- WB — только отзывы, нет данных о заказах
- Нет возвратов (только order_status=Отменен в Ozon, ~0.5%)

## Единица анализа
Товар (если указан product_code) или топ-N товаров портфеля.

## Метрики (считать для каждого товара отдельно)
- sales_current — заказы текущего периода (только "Получен")
- sales_previous — заказы предыдущего периода
- change_abs = sales_current - sales_previous
- change_pct = (sales_current - sales_previous) / sales_previous * 100
- cancelled_current / cancelled_previous — количество отмен
- cancel_rate_current / cancel_rate_previous — доля отмен
- days_without_sales — дней без продаж в текущем периоде
- avg_rating — средняя оценка (из отзывов, если есть)
- negative_reviews_current / negative_reviews_previous — негативные отзывы (1-2★)

## ВАЖНО по обработке данных:
1. JOIN Ozon по колонке `Артикул` (= product_code).
2. Период: `end_date = ozon['Дата публикации'].max()`, `start_date = end_date - period_days`.
3. `sales_current` = только `Статус получения == 'Получен'`.
4. `change_pct`: если `sales_previous == 0` → null (не nan, не inf).
5. Если анализируем конкретный товар (product_code указан) — фильтр по нему.
6. Выводи ВСЕ findings (до 20) полностью, без `//` комментариев, без `...` сокращений.

## Классификация priority (для топ-N падающих товаров)
- change_pct <= -50% → **critical** (падение больше половины)
- change_pct <= -30% → **high**
- change_pct <= -15% → **medium**
- иначе → не попадает в findings

## findings (обязательный формат результата)
Для каждого товара из топ-N падающих (по change_pct asc) вернуть finding:
- entity_type: "product"
- entity_id: product_code
- name: название товара
- priority: critical / high / medium (по классификации)
- reasons: конкретные цифры (["Продажи упали с 190 до 120 (-36.8%)", "Доля отмен выросла с 4% до 12%"])
- metrics: {sales_current, sales_previous, change_pct, cancel_rate_current, days_without_sales}
- recommended_action: конкретное действие ("Проверить остатки и цену", "Проанализировать отзывы")

Если анализируется один конкретный товар — верни 1 finding с полным анализом гипотез в reasons.

## Подходящий график
Заказы по дням (текущий vs предыдущий период) для топ-3 падающих товаров.

## Helper reference (файлы с реальным кодом)
Executor читает эти файлы и передаёт их исходник в LLM prompt:

- **helpers/sales.py** — функции: `load_ozon`, `normalize_ozon`, `daily_order_counts`, `compare_periods`, `top_growth`, `top_decline`, `category_growth`, `category_growth_by_type`, `faster_than_market`, `analyze_decline`, `load_product_categories`
- **helpers/stocks.py** — функции: `stockout_days`, `critical_stocks`, `out_of_stock`, `production_plan`
- **helpers/reviews.py** — функции: `load_wb_reviews`, `normalize_wb_reviews`, `negative_reviews_wb`, `negative_reviews_ozon`, `review_summary`, `reviews_requiring_response`, `recurring_complaints`