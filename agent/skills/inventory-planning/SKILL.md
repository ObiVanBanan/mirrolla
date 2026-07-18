# Skill: inventory-planning

## Назначение
Анализ остатков, расчёт дней запаса и рекомендаций по производству.

## Доступные датасеты
- **sales** — Ozon orders по дням (170K строк, 351 товар)
  - Колонки: product_code, sku_ozon, product_name, order_id, order_status, review_text, date, review_status, rating, photo_count, video_count, reply_count
- **stocks** — 1С ProductBalances (текущий snapshot остатков)
  - Колонки: product_code, name, balance
- **categories** — 1С productType
  - Колонки: product_code, catalog_name, product_type, brand, gtin, articleOzon, articleWb

## Гипотезы по умолчанию

### H1: Критические остатки (< 7 дней)
- **Датасеты:** sales, stocks
- **Метод:** Рассчитать средние дневные продажи → разделить остаток на скорость → получить дни запаса. Фильтр < 7 дней.
- **Helpers:** `daily_order_counts`, `stockout_days`, `critical_stocks`

### H2: Полный out-of-stock
- **Датасеты:** stocks
- **Метод:** Найти товары с balance = 0, у которых есть продажи (спрос есть, товара нет).
- **Helpers:** `out_of_stock`, `stockout_days`

### H3: Рекомендация по производству
- **Датасеты:** sales, stocks
- **Метод:** Рассчитать рекомендуемое производство = спрос за цикл производства + страховой запас − текущий остаток.
- **Helpers:** `daily_order_counts`, `stockout_days`, `production_plan`

### H4: Тренд спроса
- **Датасеты:** sales
- **Метод:** Оценить растёт или падает спрос на товар — это влияет на рекомендуемый объём.
- **Helpers:** `daily_order_counts`, `compare_periods`

## Ограничения
- Нет поставок в пути (считаем = 0 и указываем в limitations)
- Остатки — только текущий snapshot (нет истории остатков)
- Нет себестоимости (нельзя оценить стоимость производства)
- Цикл производства — параметр (по умолчанию 14 дней), реальный неизвестен
- Страховой запас — параметр (по умолчанию 7 дней)
- WB заказы не доступны — спрос считается только по Ozon

## Единица анализа
Товар.

## Метрики (считать для каждого товара отдельно)
- balance — текущий остаток (из balances.json, колонка `balance`)
- sales_7d — продажи за последние 7 дней (из Ozon, только "Получен", по колонке `Артикул`)
- avg_daily_sales — средние продажи в день = sales_7d / 7
- days_of_cover = balance / avg_daily_sales (если avg_daily_sales > 0; иначе days_of_cover = null)
- recommended_order — рекомендуемый заказ на 21 день = max(avg_daily_sales * 21 - balance, 0)

## ВАЖНО по обработке данных:
1. JOIN: `balances.product_code == ozon.Артикул` (balances.json колонка `product_code`, Ozon колонка `Артикул`).
2. `sales_7d.fillna(0)` после merge.
3. `days_of_cover`: если `avg_daily_sales == 0` → `None` (не nan).
4. Период: `end_date = ozon['Дата публикации'].max()` (НЕ `pd.Timestamp.now()`).
5. Фильтруй только товары, которые есть в Ozon (inner join).
6. Выводи ВСЕ findings (до 20) полностью, без `//` комментариев, без `...` сокращений.

## Классификация priority
- balance == 0 → **critical** (out_of_stock)
- days_of_cover <= 7 → **critical**
- days_of_cover <= 14 → **high**
- days_of_cover <= 30 → **medium**
- иначе → не попадает в findings

## findings (обязательный формат результата)
Для каждого товара с critical/high priority вернуть finding:
- entity_type: "product"
- entity_id: product_code (например "ЦБ-00049405")
- name: название товара
- priority: critical / high / medium
- reasons: конкретные цифры (["Остаток 4 шт, запас на 1.8 дня", "Продажи за 7 дней: 17 шт"])
- metrics: {balance, avg_daily_sales, days_of_cover, recommended_order}
- recommended_action: конкретное действие ("Заказать 42 шт на горизонт 21 день")

Вернуть до 20 наиболее критичных товаров, отсортированных по days_of_cover (asc).

## Подходящий график
Количество товаров по уровню критичности (bar chart) — опционально.

## Helper reference (файлы с реальным кодом)
Executor читает эти файлы и передаёт их исходник в LLM prompt:

- **helpers/sales.py** — функции: `load_ozon`, `daily_order_counts`, `compare_periods`
- **helpers/stocks.py** — функции: `stockout_days`, `critical_stocks`, `out_of_stock`, `production_plan`