"""
Генератор синтетических данных для smoke-теста Mirrolla AI.

Создаёт 5 тестовых товаров с ИЗВЕСТНЫМИ паттернами:
  T1 ЦБ-00013356 — падение продаж (190→120→60, -68% за 3 периода)
  T2 ЦБ-00031200 — рост продаж (50→120→240, +380%)
  T3 ЦБ-00026659 — критические остатки (balance=0, продажи 27/нед)
  T4 ЦБ-00065539 — всплеск негативных отзывов (5→1.2 рейтинг, 1★)
  T5 ЦБ-00018899 — контрольный (стабильные продажи 100, рейтинг 4.5)

Файлы:
  data/озон 17.03-16.04.xlsx  (период 1)
  data/озон 17.04-16.05.xlsx  (период 2)
  data/озон 17.05-16.06.xlsx  (период 3)
  data/Отзывы ВБ 17.03-17.06.2026.xlsx
  data/prepared/balances.json (перезаписать)

После прогона — restore originals из data/_backup_originals/
"""
import json
import os
import random
import pandas as pd
from datetime import datetime, timedelta

random.seed(42)

# === 5 тестовых товаров (реальные коды из каталога) ===
TEST_PRODUCTS = {
    "ЦБ-00013356": {
        "name": "Очищающий скраб с абрикосовой косточкой «Мирролла»®, 75 мл",
        "sku": 100000001, "type": "Косметика",
        "sales": [190, 120, 60],   # падение -68%
        "trend": "decline",
    },
    "ЦБ-00031200": {
        "name": "БАД к пище Комплекс для нормализации сна \"Гармония Сна\", 10 мл",
        "sku": 100000002, "type": "БАД",
        "sales": [50, 120, 240],    # рост +380%
        "trend": "growth",
    },
    "ЦБ-00026659": {
        "name": "Комплекс для нормализации сна \"Гармония Сна\", шип.",
        "sku": 100000003, "type": "БАД",
        "sales": [100, 110, 105],  # стабильные продажи, но остаток=0
        "trend": "stockout",
        "balance": 0,
    },
    "ЦБ-00065539": {
        "name": "БАД к пище «Комплекс для нормализации сна», капс.",
        "sku": 100000004, "type": "БАД",
        "sales": [100, 100, 100],  # продажи стабильны
        "trend": "bad_reviews",
    },
    "ЦБ-00018899": {
        "name": "Мелатонин \"Гармония сна\" 0,003 №30 капс (18)",
        "sku": 100000005, "type": "БАД",
        "sales": [100, 100, 100],  # контрольный — всё стабильно
        "trend": "control",
    },
}

# Периоды Ozon xlsx
PERIODS = [
    ("озон 17.03-16.04.xlsx", "2026-03-17", "2026-04-16"),
    ("озон 17.04-16.05.xlsx", "2026-04-17", "2026-05-16"),
    ("озон 17.05-16.06.xlsx", "2026-05-17", "2026-06-16"),
]

OZON_COLS = [
    "Артикул", "SKU", "Название товара", "Номер заказа", "Статус получения",
    "Текст отзыва", "Дата публикации", "Статус отзыва", "Оценка",
    "Количество фото", "Количество видео", "Количество ответов на отзыв",
]

WB_COLS = [
    "ID отзыва", "Дата", "Артикул продавца", "Артикул WB", "Количество звезд",
    "Бренд", "Текст отзыва", "Достоинства", "Недостатки", "Имя", "Регион",
    "Цвет", "Размер", "Полезность (количество минусов)",
    "Полезность (количество плюсов)", "Штрихкод", "Ответ",
    "ID начального отзыва", "ID дополнительного отзыва",
]


def _iso_date(d: datetime) -> str:
    """Ozon формат: 2026-03-16T21:00:07Z"""
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_ozon_period(period_idx: int, start: str, end: str) -> pd.DataFrame:
    """Сгенерировать заказы Ozon для одного периода."""
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    days = (end_dt - start_dt).days
    rows = []
    order_n = 1000000 + period_idx * 100000

    for code, info in TEST_PRODUCTS.items():
        total = info["sales"][period_idx]
        # распределить по дням равномерно с шумом
        per_day = total / days
        for day_i in range(days):
            d = start_dt + timedelta(days=day_i)
            n_today = max(0, int(random.gauss(per_day, per_day * 0.3)))
            for _ in range(n_today):
                order_n += 1
                # отзыв иногда (15%)
                has_review = random.random() < 0.15
                rows.append({
                    "Артикул": code,
                    "SKU": info["sku"],
                    "Название товара": info["name"],
                    "Номер заказа": f"OZ-{order_n}",
                    "Статус получения": "Получен" if random.random() > 0.05 else "Отменен",
                    "Текст отзыва": "" if not has_review else "Хороший товар",
                    "Дата публикации": _iso_date(d + timedelta(hours=random.randint(8, 22))),
                    "Статус отзыва": "Новый" if has_review else "",
                    "Оценка": random.choice([5, 5, 4]) if has_review else 0,
                    "Количество фото": 0, "Количество видео": 0,
                    "Количество ответов на отзыв": 0,
                })
    return pd.DataFrame(rows, columns=OZON_COLS)


def gen_wb_reviews() -> pd.DataFrame:
    """WB отзывы. T4 — всплеск негатива (1★), T5 — контроль (4-5★)."""
    rows = []
    rid = 0
    # T4 — 20 плохих отзывов 1-2★ с текстом жалоб
    for i in range(20):
        rid += 1
        d = datetime(2026, 3, 17) + timedelta(days=random.randint(0, 90))
        rows.append({
            "ID отзыва": f"WB-T4-{rid}",
            "Дата": d,
            "Артикул продавца": "ЦБ-00065539",
            "Артикул WB": 200000004,
            "Количество звезд": random.choice([1, 1, 2]),
            "Бренд": "mirrolla",
            "Текст отзыва": random.choice([
                "Ужасный товар, вызвала аллергию!",
                "Не помогает вообще, деньги на ветер.",
                "Побочные эффекты, тошнота после приема.",
                "Бесполезная добавка, не рекомендую.",
            ]),
            "Достоинства": "", "Недостатки": "Побочные эффекты",
            "Имя": f"Покупатель{rid}", "Регион": "ru",
            "Цвет": "", "Размер": 0,
            "Полезность (количество минусов)": 0,
            "Полезность (количество плюсов)": random.randint(0, 3),
            "Штрихкод": 51448920000 + rid,
            "Ответ": "", "ID начального отзыва": "",
            "ID дополнительного отзыва": "",
        })
    # T5 — 15 хороших отзывов 4-5★ (контроль)
    for i in range(15):
        rid += 1
        d = datetime(2026, 3, 17) + timedelta(days=random.randint(0, 90))
        rows.append({
            "ID отзыва": f"WB-T5-{rid}",
            "Дата": d,
            "Артикул продавца": "ЦБ-00018899",
            "Артикул WB": 200000005,
            "Количество звезд": random.choice([4, 5, 5]),
            "Бренд": "mirrolla",
            "Текст отзыва": random.choice([
                "Отлично помогает уснуть!",
                "Хороший мелатонин, принимаю курсом.",
                "Качество радует, буду брать ещё.",
            ]),
            "Достоинства": "Помогает уснуть", "Недостатки": "",
            "Имя": f"Покупатель{rid}", "Регион": "ru",
            "Цвет": "", "Размер": 0,
            "Полезность (количество минусов)": 0,
            "Полезность (количество плюсов)": random.randint(1, 10),
            "Штрихкод": 51448930000 + rid,
            "Ответ": "", "ID начального отзыва": "",
            "ID дополнительного отзыва": "",
        })
    return pd.DataFrame(rows, columns=WB_COLS)


def gen_balances() -> list:
    """Перезаписать balances.json: T3 — balance=0, остальные норм."""
    with open("data/prepared/products.json", encoding="utf-8") as f:
        products = json.load(f)

    balances = []
    for p in products:
        if p.get("isGroup"):
            continue
        code = p.get("code", "")
        if code in TEST_PRODUCTS:
            b = TEST_PRODUCTS[code].get("balance", random.randint(50, 500))
        else:
            b = random.randint(50, 500)
        balances.append({
            "product_code": code,
            "name": p.get("name", ""),
            "balance": float(b),
        })
    return balances


def main():
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/prepared", exist_ok=True)

    # 3 Ozon-файла
    for fname, start, end in PERIODS:
        df = gen_ozon_period(PERIODS.index((fname, start, end)), start, end)
        path = os.path.join("data", fname)
        df.to_excel(path, index=False)
        print(f"  {fname}: {len(df)} rows")

    # WB отзывы
    wb = gen_wb_reviews()
    wb_path = "data/Отзывы ВБ 17.03-17.06.2026.xlsx"
    wb.to_excel(wb_path, index=False)
    print(f"  {wb_path}: {len(wb)} rows")

    # balances.json
    balances = gen_balances()
    with open("data/prepared/balances.json", "w", encoding="utf-8") as f:
        json.dump(balances, f, ensure_ascii=False, indent=2)
    print(f"  balances.json: {len(balances)} products")

    # products.json НЕ трогаем — оставляем реальный каталог
    print("\n  products.json: НЕ тронут (реальный каталог)")

    print("\n=== ЗАШИТЫЕ ПАТТЕРНЫ (ожидаем найти) ===")
    print("  T1 ЦБ-00013356 — падение продаж 190→120→60 (-68%)")
    print("  T2 ЦБ-00031200 — рост продаж 50→120→240 (+380%)")
    print("  T3 ЦБ-00026659 — критический остаток (balance=0), продажи ~105/период")
    print("  T4 ЦБ-00065539 — 20 негативных отзывов 1-2★")
    print("  T5 ЦБ-00018899 — контроль: стабильные продажи 100, отзывы 4-5★")


if __name__ == "__main__":
    main()