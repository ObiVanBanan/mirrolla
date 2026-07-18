"""
helpers/sales.py — Аналитика продаж по Ozon-выгрузкам.

Нормализация данных + расчёт периодов, роста/падения, сравнение с категорией.

 Источник: data/озон *.xlsx (3 файла, 170K строк)
 Колонки: см. data/data_research.md
 Ключ: Артикул (ЦБ-XXXXXXXX / ФР-XXXXXXXX)
"""

import pandas as pd
import os
import json
from typing import Optional

# === Категории (productType из 1С) ===

def load_product_categories(data_dir: str = "data") -> pd.DataFrame:
    """
    Загрузить каталог товаров из data/prepared/products.json
    (получен через 1C ProductInformation, см. data/api_research.md).

    Returns:
        DataFrame: product_code, name, product_type, brand, gtin, ...
    """
    path = os.path.join(data_dir, "prepared", "products.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"products.json not found at {path}. "
            "Run: python -c \"from client.onec_client import OneCClient; "
            "c=OneCClient(); import json; "
            "data=c._post('ProductInformation',[]); "
            "open('data/prepared/products.json','w',encoding='utf-8').write(json.dumps(data, ensure_ascii=False))\""
        )
    with open(path, "r", encoding="utf-8") as f:
        products = json.load(f)
    df = pd.DataFrame(products)
    df = df.rename(columns={"code": "product_code", "name": "catalog_name",
                            "productType": "product_type"})
    return df[["product_code", "catalog_name", "product_type",
               "brand", "gtin", "articleOzon", "articleWb"]]


# === Нормализация ===

COLUMN_MAP = {
    "Артикул": "product_code",
    "SKU": "sku_ozon",
    "Название товара": "product_name",
    "Номер заказа": "order_id",
    "Статус получения": "order_status",
    "Текст отзыва": "review_text",
    "Дата публикации": "date",
    "Статус отзыва": "review_status",
    "Оценка": "rating",
    "Количество фото": "photo_count",
    "Количество видео": "video_count",
    "Количество ответов на отзыв": "reply_count",
}


def load_ozon(data_dir: str = "data") -> pd.DataFrame:
    """
    Загрузить все 3 Ozon-файла, объединить, нормализовать колонки.

    Returns:
        DataFrame with columns: product_code, sku_ozon, product_name,
        order_id, order_status, review_text, date (datetime),
        review_status, rating, photo_count, video_count, reply_count
    """
    files = [
        "озон 17.03-16.04.xlsx",
        "озон 17.04-16.05.xlsx",
        "озон 17.05-16.06.xlsx",
    ]

    dfs = []
    for f in files:
        path = os.path.join(data_dir, f)
        if not os.path.exists(path):
            continue
        df = pd.read_excel(path)
        df["_source_file"] = f
        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"No Ozon files found in {data_dir}")

    df = pd.concat(dfs, ignore_index=True)
    df = normalize_ozon(df)
    return df


def normalize_ozon(df: pd.DataFrame) -> pd.DataFrame:
    """
    Нормализовать Ozon DataFrame:
    - Переименовать колонки
    - Парсить дату (ISO 8601 UTC → datetime)
    - order_status: Получен → delivered, Отменен → cancelled
    - Удалить дубликаты на стыке файлов (по order_id + product_code)
    """
    df = df.rename(columns=COLUMN_MAP)

    # Parse date: "2026-03-16T21:00:07Z" → datetime
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)

    # Normalize order_status
    status_map = {"Получен": "delivered", "Отменен": "cancelled"}
    df["order_status"] = df["order_status"].map(status_map).fillna(df["order_status"])

    # Remove duplicates at file boundaries (same order + product)
    before = len(df)
    df = df.drop_duplicates(subset=["order_id", "product_code"], keep="first")
    deduped = before - len(df)
    if deduped > 0:
        print(f"  [normalize] Removed {deduped} duplicate rows (order_id + product_code)")

    # Sort by date
    df = df.sort_values("date").reset_index(drop=True)
    return df


# === Аналитика ===

def daily_order_counts(
    df: pd.DataFrame,
    delivered_only: bool = True,
) -> pd.DataFrame:
    """
    Посуточное количество заказов по каждому товару.

    Args:
        df: normalized Ozon DataFrame
        delivered_only: только доставленные заказы (default True)

    Returns:
        DataFrame: product_code, product_name, date, orders
    """
    if delivered_only:
        df = df[df["order_status"] == "delivered"]

    daily = (
        df.groupby(["product_code", "product_name", df["date"].dt.date])
        .size()
        .reset_index(name="orders")
        .rename(columns={"date": "date"})
    )
    daily["date"] = pd.to_datetime(daily["date"])
    return daily


def compare_periods(
    df: pd.DataFrame,
    product_code: Optional[str] = None,
    current_days: int = 14,
    end_date: Optional[str] = None,
    delivered_only: bool = True,
) -> pd.DataFrame:
    """
    Сравнить текущий и предыдущий период равной длины.

    Args:
        df: normalized Ozon DataFrame
        product_code: если указан — только этот товар, иначе все
        current_days: длительность периода в днях
        end_date: конец текущего периода (YYYY-MM-DD), иначе max date
        delivered_only: только доставленные

    Returns:
        DataFrame: product_code, product_name,
                   current_orders, previous_orders, change_abs, change_pct
    """
    if delivered_only:
        df = df[df["order_status"] == "delivered"]

    if product_code:
        df = df[df["product_code"] == product_code]

    if end_date:
        end = pd.Timestamp(end_date, tz="UTC")
    else:
        end = df["date"].max()

    start_current = end - pd.Timedelta(days=current_days)
    start_previous = start_current - pd.Timedelta(days=current_days)

    current = df[(df["date"] > start_current) & (df["date"] <= end)]
    previous = df[(df["date"] > start_previous) & (df["date"] <= start_current)]

    cur_agg = current.groupby(["product_code", "product_name"]).size().reset_index(name="current_orders")
    prev_agg = previous.groupby(["product_code", "product_name"]).size().reset_index(name="previous_orders")

    result = cur_agg.merge(prev_agg, on=["product_code", "product_name"], how="outer").fillna(0)

    result["change_abs"] = result["current_orders"] - result["previous_orders"]
    # Avoid division by zero
    result["change_pct"] = result.apply(
        lambda r: round((r["change_abs"] / r["previous_orders"] * 100), 1)
        if r["previous_orders"] > 0 else 0.0,
        axis=1,
    )

    return result.sort_values("change_pct", ascending=False).reset_index(drop=True)


def top_growth(
    df: pd.DataFrame,
    current_days: int = 14,
    end_date: Optional[str] = None,
    min_orders: int = 10,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Топ-N растущих товаров по % роста заказов.

    Args:
        min_orders: минимум заказов в текущем периоде (фильтр маленькой базы)
        top_n: сколько вернуть
    """
    result = compare_periods(df, current_days=current_days, end_date=end_date)
    result = result[result["current_orders"] >= min_orders]
    result = result.sort_values("change_pct", ascending=False)
    return result.head(top_n).reset_index(drop=True)


def top_decline(
    df: pd.DataFrame,
    current_days: int = 14,
    end_date: Optional[str] = None,
    min_orders: int = 10,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Топ-N падающих товаров по % падения заказов.
    """
    result = compare_periods(df, current_days=current_days, end_date=end_date)
    result = result[result["current_orders"] >= min_orders]
    result = result.sort_values("change_pct", ascending=True)
    return result.head(top_n).reset_index(drop=True)


def category_growth(
    df: pd.DataFrame,
    current_days: int = 14,
    end_date: Optional[str] = None,
) -> dict:
    """
    Рост всего портфеля Mirrolla (как proxy для «рынка»).

    Returns:
        {current_orders, previous_orders, change_pct}
    """
    result = compare_periods(df, current_days=current_days, end_date=end_date)
    cur = result["current_orders"].sum()
    prev = result["previous_orders"].sum()
    change = round((cur - prev) / prev * 100, 1) if prev > 0 else 0.0
    return {
        "current_orders": int(cur),
        "previous_orders": int(prev),
        "change_pct": change,
    }


def category_growth_by_type(
    df: pd.DataFrame,
    categories: pd.DataFrame,
    current_days: int = 14,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Рост по категориям (productType из 1С): Косметика, БАД, etc.

    Returns:
        DataFrame: product_type, current_orders, previous_orders, change_pct
    """
    result = compare_periods(df, current_days=current_days, end_date=end_date)
    result = result.merge(
        categories[["product_code", "product_type"]],
        on="product_code",
        how="left",
    )

    cat = (
        result.groupby("product_type")
        .agg(
            current_orders=("current_orders", "sum"),
            previous_orders=("previous_orders", "sum"),
        )
        .reset_index()
    )
    cat["change_pct"] = cat.apply(
        lambda r: round((r["current_orders"] - r["previous_orders"]) / r["previous_orders"] * 100, 1)
        if r["previous_orders"] > 0 else 0.0,
        axis=1,
    )
    return cat.sort_values("change_pct", ascending=False).reset_index(drop=True)


def faster_than_market(
    df: pd.DataFrame,
    categories: pd.DataFrame,
    current_days: int = 14,
    end_date: Optional[str] = None,
    min_orders: int = 10,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Товары, растущие быстрее своей категории.

    Сравнивает % роста товара с % роста его категории (productType).
    Возвращает товары, где рост товара > рост категории.
    """
    # Per-product growth
    product = compare_periods(df, current_days=current_days, end_date=end_date)
    product = product[product["current_orders"] >= min_orders]
    product = product.merge(
        categories[["product_code", "product_type"]],
        on="product_code",
        how="left",
    )

    # Per-category growth
    cat_growth = category_growth_by_type(df, categories, current_days, end_date)
    cat_map = dict(zip(cat_growth["product_type"], cat_growth["change_pct"]))

    product["category_change_pct"] = product["product_type"].map(cat_map).fillna(0)
    product["faster_than_category"] = product["change_pct"] > product["category_change_pct"]
    product["delta_vs_category"] = (product["change_pct"] - product["category_change_pct"]).round(1)

    result = product[product["faster_than_category"]].copy()
    result = result.sort_values("delta_vs_category", ascending=False)
    return result.head(top_n).reset_index(drop=True)


def analyze_decline(
    df: pd.DataFrame,
    product_code: str,
    balances: Optional[pd.DataFrame] = None,
    wb_reviews: Optional[pd.DataFrame] = None,
    categories: Optional[pd.DataFrame] = None,
    current_days: int = 14,
    end_date: Optional[str] = None,
) -> dict:
    """
    Комбо-функция: почему снизились продажи товара?

    Проверяет гипотезы:
      H1 — дефицит остатков (stockout)
      H2 — рост негативных отзывов
      H3 — падение всей категории
      H4 — общее падение портфеля
      H5 — цена (недоступно, фиксируем как ограничение)

    Args:
        df: normalized Ozon DataFrame
        product_code: код товара (ЦБ-XXXXXXXX)
        balances: DataFrame из 1С ProductBalances
        wb_reviews: WB reviews DataFrame
        categories: 1С catalog with product_type

    Returns:
        dict с подтверждёнными/неподтверждёнными гипотезами
    """
    result = {
        "product_code": product_code,
        "question": "Почему снизились продажи?",
        "hypotheses": {},
        "limitations": [],
    }

    # Sales change
    periods = compare_periods(df, product_code=product_code,
                              current_days=current_days, end_date=end_date)
    if periods.empty or len(periods) == 0:
        result["error"] = "Товар не найден в данных"
        return result

    row = periods.iloc[0]
    cur = int(row["current_orders"])
    prev = int(row["previous_orders"])
    change = float(row["change_pct"])
    product_name = str(row["product_name"])

    result["product_name"] = product_name
    result["current_orders"] = cur
    result["previous_orders"] = prev
    result["change_pct"] = change

    if change >= 0:
        result["verdict"] = "Продажи не снизились"
        return result

    result["verdict"] = f"Продажи снизились на {abs(change):.1f}%"

    # H1: Stockout
    if balances is not None:
        bal_row = balances[balances["product_code"] == product_code]
        if not bal_row.empty:
            balance = int(bal_row.iloc[0]["balance"])
            if balance == 0:
                result["hypotheses"]["H1_stockout"] = {
                    "confirmed": True,
                    "detail": "Остаток = 0, товар отсутствует на складе",
                }
            elif balance < 20:
                result["hypotheses"]["H1_stockout"] = {
                    "confirmed": True,
                    "detail": f"Критически низкий остаток: {balance} шт",
                }
            else:
                result["hypotheses"]["H1_stockout"] = {
                    "confirmed": False,
                    "detail": f"Остаток: {balance} шт — достаточный",
                }
        else:
            result["hypotheses"]["H1_stockout"] = {
                "confirmed": None,
                "detail": "Товар не найден в остатках 1С",
            }
    else:
        result["hypotheses"]["H1_stockout"] = {
            "confirmed": None,
            "detail": "Данные об остатках недоступны",
        }

    # H2: Negative reviews growth
    if wb_reviews is not None:
        prod_reviews = wb_reviews[wb_reviews["product_code"] == product_code].copy()
        if not prod_reviews.empty:
            # Use Ozon's max date as reference, make it tz-naive for WB comparison
            if end_date:
                end = pd.Timestamp(end_date)
            else:
                end = df["date"].max().tz_localize(None)  # tz-naive for WB
            start_current = end - pd.Timedelta(days=current_days)
            start_previous = start_current - pd.Timedelta(days=current_days)

            cur_neg = prod_reviews[
                (prod_reviews["date"] > start_current) & (prod_reviews["date"] <= end) & (prod_reviews["rating"] <= 2)
            ]
            prev_neg = prod_reviews[
                (prod_reviews["date"] > start_previous) & (prod_reviews["date"] <= start_current) & (prod_reviews["rating"] <= 2)
            ]
            neg_growth = len(cur_neg) - len(prev_neg)
            result["hypotheses"]["H2_negative_reviews"] = {
                "confirmed": neg_growth > 0,
                "detail": f"Негативных отзывов: {len(cur_neg)} (тек.) vs {len(prev_neg)} (пред.), рост: {neg_growth:+d}",
            }
        else:
            result["hypotheses"]["H2_negative_reviews"] = {
                "confirmed": False,
                "detail": "Отзывов WB по товару нет",
            }
    else:
        result["hypotheses"]["H2_negative_reviews"] = {
            "confirmed": None,
            "detail": "Данные отзывов WB недоступны",
        }

    # Also check Ozon reviews
    oz_reviews = df[(df["product_code"] == product_code) & (df["review_text"].notna())]
    if not oz_reviews.empty:
        if end_date:
            end = pd.Timestamp(end_date, tz="UTC")
        else:
            end = df["date"].max()
        start_current = end - pd.Timedelta(days=current_days)
        start_previous = start_current - pd.Timedelta(days=current_days)

        cur_oz_neg = oz_reviews[(oz_reviews["date"] > start_current) & (oz_reviews["date"] <= end) & (oz_reviews["rating"] <= 2)]
        prev_oz_neg = oz_reviews[(oz_reviews["date"] > start_previous) & (oz_reviews["date"] <= start_current) & (oz_reviews["rating"] <= 2)]
        oz_neg_growth = len(cur_oz_neg) - len(prev_oz_neg)
        if oz_neg_growth > 0:
            result["hypotheses"]["H2_negative_reviews_ozon"] = {
                "confirmed": True,
                "detail": f"Негативных отзывов Ozon: {len(cur_oz_neg)} (тек.) vs {len(prev_oz_neg)} (пред.), рост: {oz_neg_growth:+d}",
            }

    # H3: Category decline
    if categories is not None:
        product_cat = categories[categories["product_code"] == product_code]
        if not product_cat.empty:
            ptype = product_cat.iloc[0]["product_type"]
            cat_data = df.merge(
                categories[["product_code", "product_type"]],
                on="product_code", how="left",
            )
            cat_data = cat_data[cat_data["product_type"] == ptype]
            cat_periods = compare_periods(cat_data, current_days=current_days, end_date=end_date)
            cat_cur = int(cat_periods["current_orders"].sum())
            cat_prev = int(cat_periods["previous_orders"].sum())
            cat_change = round((cat_cur - cat_prev) / cat_prev * 100, 1) if cat_prev > 0 else 0.0
            result["hypotheses"]["H3_category_decline"] = {
                "confirmed": cat_change < 0,
                "detail": f"Категория «{ptype}»: {cat_change:+.1f}% ({cat_prev}→{cat_cur})",
            }
        else:
            result["hypotheses"]["H3_category_decline"] = {
                "confirmed": None,
                "detail": "Товар не найден в каталоге 1С",
            }
    else:
        result["hypotheses"]["H3_category_decline"] = {
            "confirmed": None,
            "detail": "Категории недоступны",
        }

    # H4: Portfolio decline
    portfolio = category_growth(df, current_days=current_days, end_date=end_date)
    result["hypotheses"]["H4_portfolio_trend"] = {
        "confirmed": portfolio["change_pct"] < 0,
        "detail": f"Портфель: {portfolio['change_pct']:+.1f}% ({portfolio['previous_orders']}→{portfolio['current_orders']})",
    }

    # H5: Price — not available
    result["hypotheses"]["H5_price_change"] = {
        "confirmed": None,
        "detail": "Данные по ценам недоступны (см. docs/decisions.md R1)",
    }
    result["limitations"].append("Нет данных о ценах — невозможно проверить гипотезу об изменении цены")

    # Summary
    confirmed = [k for k, v in result["hypotheses"].items() if v.get("confirmed") is True]
    if confirmed:
        result["likely_cause"] = ", ".join(confirmed)
    else:
        result["likely_cause"] = "Явных сигналов не найдено. Возможные причины: цена, реклама, сезонность — данных нет."

    return result