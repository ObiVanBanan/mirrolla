"""
run_analytics.py — Контрольный прогон аналитики без агента.

Критерий готовности дня 1 (roadmap.md):
    «Обычный Python-скрипт уже формирует основные разделы отчёта».

Запуск:
    cd C:\\Users\\theso\\Desktop\\job\\Mirrolla
    venv\\Scripts\\activate
    python run_analytics.py
"""

import sys
import json
import pandas as pd

from helpers.sales import (
    load_ozon,
    load_product_categories,
    daily_order_counts,
    compare_periods,
    top_growth,
    top_decline,
    category_growth,
    category_growth_by_type,
    faster_than_market,
    analyze_decline,
)
from helpers.reviews import (
    load_wb_reviews,
    negative_reviews_wb,
    negative_reviews_ozon,
    review_summary,
    reviews_requiring_response,
    recurring_complaints,
)
from helpers.stocks import (
    stockout_days,
    critical_stocks,
    out_of_stock,
    production_plan,
)


def try_1c_balances():
    """Попытаться получить остатки из 1С. Если VPN недоступен — вернуть None."""
    try:
        from client.onec_client import OneCClient
        client = OneCClient()
        print("  [1С] Получение остатков...")
        balances = client.get_balances()
        print(f"  [1С] Получено {len(balances)} записей остатков")
        return balances
    except Exception as e:
        print(f"  [1С] Недоступно: {e}")
        return None


def print_section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main():
    print("=" * 70)
    print("  MIRROLLA AI — КОНТРОЛЬНЫЙ ПРОГОН АНАЛИТИКИ")
    print("=" * 70)

    # ─── 1. Данные Ozon ───
    print("\n📊 Загрузка Ozon-выгрузок...")
    ozon = load_ozon("data")
    print(f"  Загружено: {len(ozon)} строк, {ozon['product_code'].nunique()} товаров")
    print(f"  Период: {ozon['date'].min().date()} → {ozon['date'].max().date()}")

    daily = daily_order_counts(ozon)
    print(f"  Посуточных записей: {len(daily)}")

    # ─── 2. Категории из 1С ───
    print("\n🏷  Загрузка категорий из 1С каталога...")
    try:
        categories = load_product_categories("data")
        print(f"  Загружено: {len(categories)} товаров, "
              f"{categories['product_type'].nunique()} категорий")
        print(f"  Категории: {categories['product_type'].value_counts().to_dict()}")
    except FileNotFoundError as e:
        print(f"  ⚠ {e}")
        categories = None

    # ─── 3. Данные WB ───
    print("\n📝 Загрузка WB-отзывов...")
    wb = load_wb_reviews("data")
    print(f"  Загружено: {len(wb)} отзывов, {wb['product_code'].nunique()} товаров")

    # ─── 4. Остатки 1С ───
    print("\n📦 Остатки из 1С...")
    balances = try_1c_balances()

    # ─── 5. Топ роста ───
    print_section("ТОП-10 РАСТУЩИХ ТОВАРОВ")
    growth = top_growth(ozon, current_days=14, min_orders=10, top_n=10)
    if growth.empty:
        print("  Нет данных")
    else:
        for _, row in growth.iterrows():
            print(f"  {row['product_code']:15s}  {row['change_pct']:+6.1f}%  "
                  f"  {int(row['previous_orders'])}→{int(row['current_orders'])}  "
                  f"  {str(row['product_name'])[:50]}")

    # ─── 6. Топ падения ───
    print_section("ТОП-10 ПАДАЮЩИХ ТОВАРОВ")
    decline = top_decline(ozon, current_days=14, min_orders=10, top_n=10)
    if decline.empty:
        print("  Нет данных")
    else:
        for _, row in decline.iterrows():
            print(f"  {row['product_code']:15s}  {row['change_pct']:+6.1f}%  "
                  f"  {int(row['previous_orders'])}→{int(row['current_orders'])}  "
                  f"  {str(row['product_name'])[:50]}")

    # ─── 7. Рост по категориям ───
    print_section("РОСТ ПО КАТЕГОРИЯМ (productType)")
    if categories is not None:
        cat_growth = category_growth_by_type(ozon, categories, current_days=14)
        for _, row in cat_growth.iterrows():
            ptype = row["product_type"] if pd.notna(row["product_type"]) else "(без категории)"
            print(f"  {ptype:20s}  {row['change_pct']:+6.1f}%  "
                  f"  {int(row['previous_orders'])}→{int(row['current_orders'])}")
    else:
        print("  ⚠ Категории недоступны")

    # ─── 8. Быстрее рынка (= быстрее своей категории) ───
    print_section("ТОП-10 ТОВАРОВ БЫСТРЕЕ СВОЕЙ КАТЕГОРИИ")
    if categories is not None:
        fast = faster_than_market(ozon, categories, current_days=14, min_orders=10, top_n=10)
        if fast.empty:
            print("  Нет товаров быстрее категории")
        else:
            for _, row in fast.iterrows():
                ptype = row.get("product_type", "?")
                if pd.isna(ptype):
                    ptype = "?"
                print(f"  {row['product_code']:15s}  товар: {row['change_pct']:+6.1f}%  "
                      f"кат: {row['category_change_pct']:+6.1f}%  "
                      f"Δ: {row['delta_vs_category']:+6.1f}pp  "
                      f"[{ptype}]")
    else:
        print("  ⚠ Категории недоступны — используем общий рост портфеля")
        cat = category_growth(ozon, current_days=14)
        print(f"  Портфель: {cat['change_pct']:+.1f}%")

    # ─── 9. Критические остатки ───
    print_section("КРИТИЧЕСКИЕ ОСТАТКИ (< 7 дней)")
    if balances is not None:
        crit = critical_stocks(balances, daily, threshold_days=7)
        if crit.empty:
            print("  Нет критических остатков")
        else:
            for _, row in crit.head(15).iterrows():
                print(f"  {row['product_code']:15s}  остаток: {int(row['balance']):6d}  "
                      f"дней: {row['days_of_stock']:6.1f}  "
                      f"{str(row.get('name', ''))[:40]}")
    else:
        print("  ⚠ 1С недоступен — остатки не получены")

    # ─── 10. План производства ───
    print_section("ПЛАН ПРОИЗВОДСТВА (цикл 14 дней, страховой запас 7 дней)")
    if balances is not None:
        plan = production_plan(balances, daily, production_cycle_days=14, safety_stock_days=7)
        if plan.empty:
            print("  Нет рекомендаций")
        else:
            for _, row in plan.head(15).iterrows():
                print(f"  {row['product_code']:15s}  произвести: {int(row['recommended_production']):6d}  "
                      f"остаток: {int(row['balance']):6d}  "
                      f"{str(row.get('name', ''))[:40]}")
    else:
        print("  ⚠ 1С недоступен — план не построен")

    # ─── 11. Негативные отзывы WB ───
    print_section("НЕГАТИВНЫЕ ОТЗЫВЫ WB (1-2★)")
    neg_wb = negative_reviews_wb(wb, max_rating=2, top_n=15)
    if neg_wb.empty:
        print("  Нет негативных отзывов WB")
    else:
        for _, row in neg_wb.iterrows():
            text = str(row.get("display_text", ""))[:60]
            print(f"  {row['product_code']:15s}  ★{int(row['rating'])}  {text}")

    # ─── 12. Негативные отзывы Ozon ───
    print_section("НЕГАТИВНЫЕ ОТЗЫВЫ OZON (1-2★, с текстом)")
    neg_oz = negative_reviews_ozon(ozon, max_rating=2, top_n=15)
    if neg_oz.empty:
        print("  Нет негативных отзывов Ozon")
    else:
        for _, row in neg_oz.iterrows():
            text = str(row.get("review_text", ""))[:60]
            print(f"  {row['product_code']:15s}  ★{int(row['rating'])}  {text}")

    # ─── 13. Повторяющиеся жалобы ───
    print_section("ПОВТОРЯЮЩИЕСЯ ЖАЛОБЫ (топ по кол-ву негативных)")
    recurring = recurring_complaints(wb, max_rating=3, top_n=10)
    if recurring.empty:
        print("  Нет повторяющихся жалоб")
    else:
        for _, row in recurring.iterrows():
            samples = " | ".join(str(t)[:40] for t in row["sample_texts"][:2])
            print(f"  {row['product_code']:15s}  жалоб: {int(row['complaint_count']):3d}  "
                  f"ср.★: {row['avg_rating']:.1f}  {samples}")

    # ─── 14. Сводка по отзывам ───
    print_section("СВОДКА ПО ОТЗЫВАМ (топ по негативным)")
    summary = review_summary(wb_df=wb, ozon_df=ozon)
    if not summary.empty:
        for _, row in summary.head(15).iterrows():
            print(f"  {row['product_code']:15s}  "
                  f"всего: {int(row['total_reviews']):5d}  "
                  f"негативных: {int(row['total_negative']):3d}  "
                  f"({row['negative_pct']:.1f}%)")

    # ─── 15. Комбо: «Почему упали продажи?» ───
    print_section("КОМБО-АНАЛИЗ: «ПОЧЕМУ УПАЛИ ПРОДАЖИ?»")
    if not decline.empty:
        # Берём топ-3 падающих товара
        for _, row in decline.head(3).iterrows():
            code = row["product_code"]
            name = str(row["product_name"])[:40]
            print(f"\n  ── {code} {name} ──")
            result = analyze_decline(
                ozon, code,
                balances=balances,
                wb_reviews=wb,
                categories=categories,
                current_days=14,
            )
            print(f"  Вердикт: {result.get('verdict', '?')}")
            print(f"  Заказы: {result.get('previous_orders', '?')} → {result.get('current_orders', '?')} "
                  f"({result.get('change_pct', '?'):+.1f}%)")
            for hname, hval in result.get("hypotheses", {}).items():
                status = "✅" if hval.get("confirmed") is True else ("❌" if hval.get("confirmed") is False else "❓")
                print(f"  {status} {hname}: {hval.get('detail', '')}")
            print(f"  Вероятная причина: {result.get('likely_cause', '?')}")
            if result.get("limitations"):
                print(f"  Ограничения: {'; '.join(result['limitations'])}")

    print("\n" + "=" * 70)
    print("  ✅ КОНТРОЛЬНЫЙ ПРОГОН ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()