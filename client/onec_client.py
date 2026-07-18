"""
client/onec_client.py — Клиент тестового API 1С УНФ Mirrolla.

 Подключение: VPN + HTTP (192.168.201.250)
 Auth: Basic WebAssistant:WebAssistant
 Функции: ProductInformation, ProductBalances, ProductSales

 ⚠️ Фильтр по кодам не работает — API всегда отдаёт весь список при [].
    Фильтрация на стороне приложения.

 См. data/api_research.md
"""

import requests
import pandas as pd
from typing import Optional

BASE_URL = "http://192.168.201.250/Sklad_Server/hs/WebAssistant"
AUTH = ("WebAssistant", "WebAssistant")
TIMEOUT = 60  # ProductInformation может быть 7+ MB


class OneCClient:
    """Клиент для тестового API 1С УНФ."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        auth: tuple = AUTH,
        timeout: int = TIMEOUT,
    ):
        self.base_url = base_url
        self.auth = auth
        self.timeout = timeout

    def _post(self, function: str, body: list | dict) -> list:
        """POST request to 1C API."""
        url = f"{self.base_url}/{function}"
        resp = requests.post(
            url,
            json=body,
            auth=self.auth,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    # === Product Information ===

    def get_products(self, codes: Optional[list] = None) -> pd.DataFrame:
        """
        Получить каталог товаров (дерево).

        Args:
            codes: фильтр не работает — передаётся как есть.

        Returns:
            DataFrame: только товары (isGroup=false), flatten из дерева.
            Колонки: code, name, gtin, articleOzon, articleWb, productType,
            brand, manufacturer, releaseForm, composition, и т.д.
        """
        body = codes if codes is not None else []
        data = self._post("ProductInformation", body)
        products = _flatten_tree(data)
        return pd.DataFrame(products)

    # === Product Balances ===

    def get_balances(self, codes: Optional[list] = None) -> pd.DataFrame:
        """
        Получить остатки товаров (текущий snapshot).

        Returns:
            DataFrame: product_code, name, balance
        """
        body = codes if codes is not None else []
        data = self._post("ProductBalances", body)
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.rename(columns={"code": "product_code"})
        return df

    # === Product Sales ===

    def get_sales(
        self,
        date_start: str,
        date_end: str,
        codes: Optional[list] = None,
    ) -> pd.DataFrame:
        """
        Получить продажи за период.

        Args:
            date_start: ГГГГММДД (8 цифр без разделителей!)
            date_end: ГГГГММДД
            codes: фильтр не работает, передаётся как есть

        Returns:
            DataFrame: product_code, name, quantity
        """
        body = {
            "dateStart": date_start,
            "dateEnd": date_end,
            "codes": codes if codes is not None else [],
        }
        data = self._post("ProductSales", body)
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.rename(columns={"code": "product_code"})
        return df


# === Утилиты ===

def _flatten_tree(tree: list) -> list[dict]:
    """
    Развернуть дерево номенклатуры в плоский список товаров.

    Оставляет только isGroup=false, выбрасывает группы.
    """
    products = []

    def walk(items):
        for item in items:
            if not item.get("isGroup", False):
                # Flatten children too (they should be empty for products)
                item_copy = {k: v for k, v in item.items() if k != "children"}
                products.append(item_copy)
            children = item.get("children", [])
            if children:
                walk(children)

    walk(tree)
    return products