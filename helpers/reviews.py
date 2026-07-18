"""
helpers/reviews.py — Аналитика отзывов WB и Ozon.

 Источник WB: data/Отзывы ВБ 17.03-17.06.2026.xlsx (4132 отзыва)
 Источник Ozon: внутри Ozon-выгрузок (колонки review_text, rating)
 Ключ: product_code (Артикул / Артикул продавца)
"""

import pandas as pd
import os
from typing import Optional

# === Нормализация ===

WB_COLUMN_MAP = {
    "ID отзыва": "review_id",
    "Дата": "date",
    "Артикул продавца": "product_code",
    "Артикул WB": "article_wb",
    "Количество звезд": "rating",
    "Бренд": "brand",
    "Текст отзыва": "review_text",
    "Достоинства": "pros",
    "Недостатки": "cons",
    "Имя": "author_name",
    "Регион": "region",
    "Цвет": "volume",
    "Полезность (количество минусов)": "dislikes",
    "Полезность (количество плюсов)": "likes",
    "Штрихкод": "gtin",
    "ID начального отзыва": "parent_review_id",
    "ID дополнительного отзыва": "child_review_id",
}

# Бренды с разным регистром → нормализованные
BRAND_NORMALIZE = {
    "mirrolla": "Mirrolla",
    "Mirrolla": "Mirrolla",
    "МИРРОЛЛА": "Mirrolla",
    "Мирролла": "Mirrolla",
    "911 экстренная помощь": "911 Экстренная помощь",
    "911 Экстренная помощь": "911 Экстренная помощь",
}


def load_wb_reviews(data_dir: str = "data") -> pd.DataFrame:
    """Загрузить и нормализовать WB-отзывы."""
    path = os.path.join(data_dir, "Отзывы ВБ 17.03-17.06.2026.xlsx")
    if not os.path.exists(path):
        raise FileNotFoundError(f"WB reviews file not found: {path}")

    df = pd.read_excel(path, sheet_name="feedbacks")
    df = normalize_wb_reviews(df)
    return df


def normalize_wb_reviews(df: pd.DataFrame) -> pd.DataFrame:
    """Нормализовать WB-отзывы."""
    # Drop useless columns
    drop_cols = ["Размер", "Ответ"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    # Rename
    df = df.rename(columns=WB_COLUMN_MAP)

    # Normalize brand
    df["brand"] = df["brand"].map(lambda x: BRAND_NORMALIZE.get(x, x))

    # Normalize region to uppercase
    df["region"] = df["region"].str.upper()

    # GTIN to string (preserve leading zeros if any)
    df["gtin"] = df["gtin"].astype(str).str.split(".").str[0]

    # Strip "+" suffix from product_code (e.g. "ФР-00000110+" → "ФР-00000110")
    df["product_code"] = df["product_code"].str.replace("+", "", regex=False)

    return df


# === Аналитика ===

def negative_reviews_wb(
    df: pd.DataFrame,
    max_rating: int = 2,
    top_n: int = 20,
) -> pd.DataFrame:
    """
    Негативные отзывы WB (1-2 звезды).

    Текст отзыва: если review_text пустой (nan), берём из cons (недостатки).
    Returns:
        DataFrame: review_id, date, product_code, brand, rating,
                   review_text, pros, cons, author_name
    """
    neg = df[df["rating"] <= max_rating].copy()

    # Fallback: review_text → cons → pros
    neg["display_text"] = neg["review_text"].fillna("")
    neg.loc[neg["display_text"] == "", "display_text"] = neg["cons"].fillna("")
    neg.loc[neg["display_text"] == "", "display_text"] = neg["pros"].fillna("")
    neg.loc[neg["display_text"] == "", "display_text"] = "(без текста)"

    neg = neg.sort_values("rating").reset_index(drop=True)
    return neg.head(top_n)


def negative_reviews_ozon(
    ozon_df: pd.DataFrame,
    max_rating: int = 2,
    top_n: int = 20,
) -> pd.DataFrame:
    """
    Негативные отзывы Ozon (1-2 звезды), только с текстом.

    Args:
        ozon_df: normalized Ozon DataFrame (from helpers.sales)
    """
    neg = ozon_df[
        (ozon_df["rating"] <= max_rating)
        & (ozon_df["review_text"].notna())
    ].copy()
    neg = neg.sort_values("rating").reset_index(drop=True)
    return neg.head(top_n)


def review_summary(
    wb_df: Optional[pd.DataFrame] = None,
    ozon_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Сводка по отзывам: средний рейтинг, кол-во отзывов, % негативных.
    По каждому товару.
    """
    frames = []

    if wb_df is not None:
        wb_summary = (
            wb_df.groupby("product_code")
            .agg(
                wb_reviews=("rating", "count"),
                wb_avg_rating=("rating", "mean"),
                wb_negative=("rating", lambda x: (x <= 2).sum()),
            )
            .reset_index()
        )
        frames.append(wb_summary)

    if ozon_df is not None:
        oz_reviews = ozon_df.copy()
        oz_summary = (
            oz_reviews.groupby("product_code")
            .agg(
                oz_reviews=("rating", "count"),
                oz_avg_rating=("rating", "mean"),
                oz_negative=("rating", lambda x: (x <= 2).sum()),
            )
            .reset_index()
        )
        frames.append(oz_summary)

    if not frames:
        return pd.DataFrame()

    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on="product_code", how="outer")

    # Combined metrics
    review_cols = [c for c in result.columns if "reviews" in c]
    neg_cols = [c for c in result.columns if "negative" in c]
    result["total_reviews"] = result[review_cols].sum(axis=1)
    result["total_negative"] = result[neg_cols].sum(axis=1)
    result["negative_pct"] = result.apply(
        lambda r: round(r["total_negative"] / r["total_reviews"] * 100, 1)
        if r["total_reviews"] > 0 else 0.0,
        axis=1,
    )

    return result.sort_values("total_negative", ascending=False).reset_index(drop=True)


def reviews_requiring_response(
    wb_df: pd.DataFrame,
    max_rating: int = 2,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Отзывы, требующие реакции: негативные + с текстом, без ответа продавца.
    Ранжирование: оценка (ниже = приоритетнее), наличие текста.
    """
    neg = negative_reviews_wb(wb_df, max_rating=max_rating, top_n=9999)
    # Prioritize: lowest rating, then has real text
    neg["has_text"] = (neg["review_text"].notna() & (neg["review_text"] != "")).astype(int)
    neg = neg.sort_values(["rating", "has_text"], ascending=[True, False]).reset_index(drop=True)
    return neg.head(top_n)


def recurring_complaints(
    wb_df: pd.DataFrame,
    max_rating: int = 3,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Повторяющиеся жалобы по товарам: группирует негативные отзывы
    по product_code и показывает товары с наибольшим числом жалоб.

    Returns:
        DataFrame: product_code, brand, complaint_count, avg_rating,
                   sample_complaints (list of texts)
    """
    neg = wb_df[wb_df["rating"] <= max_rating].copy()

    # Build display text
    neg["display_text"] = neg["review_text"].fillna("")
    neg.loc[neg["display_text"] == "", "display_text"] = neg["cons"].fillna("")
    neg.loc[neg["display_text"] == "", "display_text"] = neg["pros"].fillna("")

    grouped = neg.groupby("product_code").agg(
        complaint_count=("rating", "count"),
        avg_rating=("rating", "mean"),
        brand=("brand", "first"),
        sample_texts=("display_text", lambda x: list(x.head(3))),
    ).reset_index()

    grouped = grouped.sort_values("complaint_count", ascending=False)
    return grouped.head(top_n).reset_index(drop=True)