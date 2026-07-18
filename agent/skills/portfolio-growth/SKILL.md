# Skill: portfolio-growth

## Назначение
Анализ роста/падения портфеля товаров, сравнение с категорией (рынком).

## Доступные датасеты
- **sales** — Ozon orders по дням (170K строк, 351 товар, период 17.03–16.06.2026)
  - Колонки: product_code, sku_ozon, product_name, order_id, order_status, review_text, date, review_status, rating, photo_count, video_count, reply_count
- **categories** — 1С productType
  - Колонки: product_code, catalog_name, product_type, brand, gtin, articleOzon, articleWb

## Гипотезы по умолчанию

### H1: Топ-10 растущих товаров
- **Датасеты:** sales
- **Метод:** Сравнить заказы текущего периода с предыдущим, отсортировать по % роста. Фильтр min_orders для отсечения маленькой базы.
- **Helpers:** `load_ozon`, `compare_periods`, `top_growth`

### H2: Топ-10 падающих товаров
- **Датасеты:** sales
- **Метод:** То же, но по убыванию.
- **Helpers:** `load_ozon`, `compare_periods`, `top_decline`

### H3: Рост по категориям (productType)
- **Датасеты:** sales, categories
- **Метод:** Группировать продажи по productType, сравнить периоды.
- **Helpers:** `load_ozon`, `compare_periods`, `category_growth_by_type`, `load_product_categories`

### H4: Товары быстрее своей категории
- **Датасеты:** sales, categories
- **Метод:** Для каждого товара сравнить его рост с ростом его категории. Delta = товар_рост − категория_рост.
- **Helpers:** `load_ozon`, `compare_periods`, `faster_than_market`, `load_product_categories`

## Ограничения
- "Рынок" = категория товаров внутри данных Mirrolla (не реальный рынок WB/Ozon)
- Нет данных о долях рынка
- Нет цен → рост измеряется в заказах, не в выручке
- WB заказы не доступны — только Ozon
- Фильтр min_orders важен: товар с 1→3 заказами показывает +200%, но это шум

## Единица анализа
Товар и период.

## Метрики (считать для каждого товара отдельно)
- sales_current — заказы текущего периода (только "Получен")
- sales_previous — заказы предыдущего периода
- change_pct = (sales_current - sales_previous) / sales_previous * 100
- product_type — категория товара (из products.json, поле `productType`)
- category_growth — рост категории товара (агрегат по product_type)
- excess_growth = product_growth - category_growth (товар растёт быстрее своей категории)
- market_share_current — доля товара в категории (текущий период)
- market_share_previous — доля товара в категории (предыдущий период)

## ВАЖНО по обработке данных:
1. JOIN Ozon по `Артикул`, categories по `product_code` == `Артикул`.
2. Период: `end_date = ozon['Дата публикации'].max()`, `start_date = end_date - period_days`.
3. `sales_current` = только `Статус получения == 'Получен'`.
4. `change_pct`: если `sales_previous == 0` → null.
5. Фильтр min_orders: `sales_current >= 10` (отсечь шум).
6. "Рынок" = категория (productType), НЕ реальный рынок — явно указывай в answer.
7. Выводи ВСЕ findings (до 20) полностью, без `//` комментариев, без `...` сокращений.

## Классификация priority (для топ растущих)
- excess_growth >= 50 (товар растёт быстрее категории на 50%+) → **critical** (лидер роста)
- excess_growth >= 25 → **high**
- excess_growth >= 10 → **medium**
- иначе → не попадает в findings

## findings (обязательный формат результата)
Для вопроса «растут быстрее рынка» — топ-N товаров по excess_growth (desc):
- entity_type: "product"
- entity_id: product_code
- name: название товара
- priority: critical / high / medium
- reasons: ["Рост +120% vs категории +30% (excess +90%)", "Доля в категории выросла с 5% до 8%"]
- metrics: {sales_current, sales_previous, change_pct, category_growth, excess_growth, market_share_current}
- recommended_action: "Увеличить остатки", "Расширить ассортимент в этой категории"

Для вопроса «топ растущих/падающих» — топ-N по change_pct:
- reasons: ["Продажи выросли с 100 до 250 (+150%)"]

## Подходящий график
Топ-10 товаров: change_pct (bar chart, rot 45), цвет по excess_growth.

## Helper reference (файлы с реальным кодом)
Executor читает эти файлы и передаёт их исходник в LLM prompt:

- **helpers/sales.py** — функции: `load_ozon`, `daily_order_counts`, `compare_periods`, `top_growth`, `top_decline`, `category_growth`, `category_growth_by_type`, `faster_than_market`, `load_product_categories`