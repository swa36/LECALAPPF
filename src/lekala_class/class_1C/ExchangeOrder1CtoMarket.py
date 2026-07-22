import json
from decimal import Decimal
from typing import Dict, List

import requests
from django.conf import settings
from requests.auth import HTTPBasicAuth


class OrderMarketplaceTo1C:
    """Унифицированный класс для передачи заказов маркетплейсов в 1С."""

    BASE_URL = settings.BASE_URL_1C_HS.rstrip("/") + "/"

    PLATFORM_MAPPING = {
        "orderali": {
            "name": "Aliexpress",
            "number_field": "number_ali",
            "name_template": lambda o: f"{getattr(o, 'name_shop', 'Aliexpress')} {o.name} {o.family}",
            "number_1C": lambda o: f"AL00-{o.number_ali}",
        },
        "orderavito": {
            "name": "Avito",
            "number_field": "number_avito",
            "name_template": lambda o: f"Avito {o.number_avito}",
            "number_1C": lambda o: o.number_avito,
        },
        "orderozon": {
            "name": "OZON",
            "number_field": "number_ozon",
            "name_template": lambda o: f"{getattr(o, 'name_shop', 'OZON')} {o.number_ozon}",
            "number_1C": lambda o: f"OZ00-{o.number_ozon}",
        },
        "orderwb": {
            "name": "Wildberries",
            "number_field": "number_WB",
            "name_template": lambda o: f"{getattr(o, 'name_shop', 'Wildberries')} {o.number_WB}",
            "number_1C": lambda o: f"WB00-{o.number_WB}",
        },
        "orderym": {
            "name": "YandexMarket",
            "number_field": "number_ym",
            "name_template": lambda o: f"{getattr(o, 'name_shop', 'YandexMarket')} {o.number_ym}",
            "number_1C": lambda o: f"YA00-{o.number_ym}",
        },
    }

    def __init__(self, order):
        self.order = order
        self.platform_info = self._get_platform_info()
        self.auth = HTTPBasicAuth(settings.LOGIN_1C, settings.PASSWORD_1C)

    def _get_platform_info(self) -> Dict:
        model_name = self.order._meta.model_name.lower()
        return self.PLATFORM_MAPPING.get(
            model_name,
            {
                "name": "Unknown",
                "number_field": None,
                "name_template": lambda o: "Unknown",
            },
        )

    def _get_order_items(self) -> List:
        if hasattr(self.order, "items"):
            return list(self.order.items.all())
        return [self.order]

    def _generate_order_comment(self, order_items: List) -> str:
        if self.platform_info["name"] == "Avito":
            adv_names = [
                item.name_advertisement_item
                for item in order_items
                if hasattr(item, "name_advertisement_item")
            ]
            return f"{self.platform_info['name']}\n" + "\n".join(adv_names)
        number = getattr(self.order, self.platform_info["number_field"], "")
        return f"{self.platform_info['name']}\n{number}"

    def _number_value(self, value):
        if isinstance(value, Decimal):
            if value == value.to_integral_value():
                return int(value)
            return float(value)
        return value

    def _prepare_product_data(self, item) -> Dict:
        product = item.product
        quantity = getattr(item, "quantity", 1)
        price = getattr(item, "price", self.order.price)
        return {
            "Номенклатура_Key": str(product.uuid_1C)
            if product
            else "00000000-0000-0000-0000-000000000000",
            "Количество": int(quantity),
            "Цена": self._number_value(price),
        }

    def prepare_order_data(self) -> Dict:
        order_items = self._get_order_items()
        data = {
            "Покупатель": self.platform_info["name_template"](self.order),
            "Комментарий": self._generate_order_comment(order_items),
            "СуммаДокумента": self._number_value(self.order.price),
            "Товары": [self._prepare_product_data(item) for item in order_items],
        }
        number_factory = self.platform_info.get("number_1C")
        if number_factory:
            data["Номер"] = number_factory(self.order)
        return data

    def send_to_1c(self, post: bool = False) -> bool:
        order_data = self.prepare_order_data()
        url = f"{self.BASE_URL}order"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",
        }
        body = json.dumps(order_data, ensure_ascii=False).encode("utf-8")

        try:
            response = requests.post(
                url,
                auth=self.auth,
                data=body,
                headers=headers,
                timeout=10,
            )
            try:
                response_data = response.json()
            except ValueError:
                response_data = {}

            if response.status_code >= 400 or response_data.get("code"):
                print(f"Ошибка отправки заказа в 1С: {response.status_code} {response_data}")
                return False

            response.raise_for_status()
            if not response_data.get("ref_key"):
                print(f"1С не вернула ref_key заказа: {response_data}")
                return False

            self.order.exchange_1c = True
            self.order.save(update_fields=["exchange_1c"])
            return True
        except requests.exceptions.RequestException as exc:
            print(f"Ошибка отправки заказа в 1С: {exc}")
            return False
