"""
helpers/stocks.py — Аналитика остатков и план производства.

Источник остатков: 1С API ProductBalances (через client.onec_client.OneCClient)
Источник продаж: Ozon-выгрузки (helpers.sales)

Формулы MVP (из roadmap.md):
    дни запаса = остаток / средние_продажи_в_день
    recommended_production = спрос_за_цикл + страховой_запас - текущий_остаток
"""

import pandas as pd
from typing import Optional


def stockout_days(
    balances: pd.DataFrame,
    daily_sales: pd.DataFrame,
) -> pd.DataFrame:
    """
    Рассчитать количество дней до окончания остатка.

    Args:
        balances: DataFrame с columns [product_code, name, balance]
                  (из 1С ProductBalances)
        daily_sales: DataFrame с columns [product_code, product_name, date, orders]
                     (из helpers.sales.daily_order_counts)

    Returns:
        DataFrame: product_code, name, balance, avg_daily_sales, days_of_stock
    """
    # Средние продажи в день по товару
    avg_sales = (
        daily_sales.groupby("product_code")["orders"]
        .mean()
        .reset_index()
        .rename(columns={"orders": "avg_daily_sales"})
    )

    result = balances.merge(avg_sales, on="product_code", how="left")
    result["avg_daily_sales"] = result["avg_daily_sales"].fillna(0)

    # Days of stock
    result["days_of_stock"] = result.apply(
        lambda r: round(r["balance"] / r["avg_daily_sales"], 1)
        if r["avg_daily_sales"] > 0 else float("inf"),
        axis=1,
    )

    return result


def critical_stocks(
    balances: pd.DataFrame,
    daily_sales: pd.DataFrame,
    threshold_days: int = 7,
) -> pd.DataFrame:
    """
    Товары с критическими остатками (дней запаса < threshold).

    Args:
        threshold_days: порог критичности в днях (default 7)
    """
    df = stockout_days(balances, daily_sales)
    df = df[df["days_of_stock"] < threshold_days]
    df = df[df["balance"] > 0]  # Только товары с ненулевым остатком
    return df.sort_values("days_of_stock").reset_index(drop=True)


def out_of_stock(
    balances: pd.DataFrame,
) -> pd.DataFrame:
    """
    Товары с нулевым остатком.
    """
    return balances[balances["balance"] == 0].reset_index(drop=True)


def production_plan(
    balances: pd.DataFrame,
    daily_sales: pd.DataFrame,
    production_cycle_days: int = 14,
    safety_stock_days: int = 7,
    min_demand_threshold: int = 0,
) -> pd.DataFrame:
    """
    Рекомендуемый объём производства.

    Формула:
        recommended = (avg_daily_sales * production_cycle_days)
                     + (avg_daily_sales * safety_stock_days)
                     - current_balance

    Args:
        production_cycle_days: цикл производства в днях (default 14)
        safety_stock_days: страховой запас в днях (default 7)
        min_demand_threshold: минимальный спрос для рекомендации (default 0)
    """
    df = stockout_days(balances, daily_sales)

    demand_cycle = df["avg_daily_sales"] * production_cycle_days
    safety = df["avg_daily_sales"] * safety_stock_days
    df["recommended_production"] = (demand_cycle + safety - df["balance"]).round(0).astype(int)

    # Only recommend if there's actual demand
    df = df[df["avg_daily_sales"] > min_demand_threshold]
    df = df[df["recommended_production"] > 0]

    df["production_cycle_days"] = production_cycle_days
    df["safety_stock_days"] = safety_stock_days

    return df.sort_values("recommended_production", ascending=False).reset_index(drop=True)