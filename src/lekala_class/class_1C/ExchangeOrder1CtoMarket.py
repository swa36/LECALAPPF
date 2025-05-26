import json
import os
from pathlib import Path
import django
from requests.auth import HTTPBasicAuth
import requests
import datetime
import pytz
from typing import Dict, List, Optional, Tuple
from lekala_ppf.settings import LOGIN_1C, PASSWORD_1C, BASE_URL_1C
from catalog.models import TypePrices


class OrderMarketplaceTo1C:
    """Унифицированный класс для передачи заказов из различных платформ в 1С."""

    # Константы для работы с API 1С
    BASE_URL = BASE_URL_1C
    DEFAULT_VALUES = {
        "Склад_Key": "e57af514-4c46-11ec-a9c8-f8cab8387a55",
        "СтавкаНДС_Key": "ef585e44-eef9-11ee-88ed-00155d46f78c",
        "ВидЦены_Key": str(TypePrices.objects.get(suffix='retail_price').uuid_1C),
    }

    # Маппинг платформ
    PLATFORM_MAPPING = {
        'orderali': {
            'name': 'Aliexpress',
            'number_field': 'number_ali',
            'name_template': lambda o: f'{o.name_shop} {o.name} {o.family}'
        },
        'orderavito': {
            'name': 'Avito',
            'number_field': 'number_avito',
            'name_template': lambda o: f'Avito {o.number_avito}'
        },
        'orderozon': {
            'name': 'OZON',
            'number_field': 'number_ozon',
            'name_template': lambda o: f'{o.name_shop} {o.number_ozon}',
            'number_1C': lambda o: f'OZ00-{o.number_ozon}'
        },
        'orderwb': {
            'name': 'Wildberries',
            'number_field': 'number_WB',
            'name_template': lambda o: f'{o.name_shop} {o.number_WB}',
            'number_1C': lambda o: f'WB00-{o.number_WB}'
        }
    }

    def __init__(self, order):
        self.order = order
        self.platform_info = self._get_platform_info()
        self.auth = HTTPBasicAuth(LOGIN_1C, PASSWORD_1C)

    def _get_platform_info(self) -> Dict:
        """Определяет информацию о платформе заказа."""
        model_name = self.order._meta.model_name.lower()
        return self.PLATFORM_MAPPING.get(model_name, {
            'name': 'Unknown',
            'number_field': None,
            'name_template': lambda o: 'Unknown'
        })

    def _get_current_datetime(self) -> str:
        """Возвращает текущую дату и время в нужном формате."""
        tz = pytz.timezone('Europe/Moscow')
        return datetime.datetime.now(tz).isoformat(timespec='seconds')[:-6]

    def _get_shipment_date(self) -> str:
        """Возвращает дату отгрузки в формате 1С."""
        return f"{datetime.date.today().isoformat()}T00:00:00"

    def create_user_1C(self) -> Tuple[str, str]:
        """Создает контрагента и партнера в 1С."""
        full_name = self.platform_info['name_template'](self.order)

        # Создаем партнера
        partner_url = f"{self.BASE_URL}Catalog_Партнеры?$format=application/json;odata=nometadata"
        partner_data = {
            "НаименованиеПолное": full_name,
            "Description": full_name,
            "Клиент": True
        }
        partner_ref = self._make_request(partner_url, partner_data)['Ref_Key']

        # Создаем контрагента
        contractor_url = f"{self.BASE_URL}Catalog_Контрагенты?$format=application/json;odata=nometadata"
        contractor_data = {
            "НаименованиеПолное": full_name,
            "Description": full_name,
            "ЮрФизЛицо": "ФизЛицо",
            "Партнер_Key": partner_ref
        }
        contractor_ref = self._make_request(contractor_url, contractor_data)['Ref_Key']

        # Сохраняем ссылки в заказе
        self.order.id_patner = partner_ref
        self.order.id_contr = contractor_ref
        self.order.save()

        print(f'USER {self.platform_info["name"]} CREATED')
        return partner_ref, contractor_ref

    def _make_request(self, url: str, data: Optional[dict] = None) -> Dict | None:
        """Выполняет HTTP-запрос к API 1С."""
        try:
            if data is None:
                response = requests.post(url, auth=self.auth, data='')
                print(f'Post {response}')
                return
            else:
                response = requests.post(url, auth=self.auth, json=data)
            response.raise_for_status()
            if response != 204:
                return response.json()
        except requests.exceptions.HTTPError as e:
             print(data, sep='\n')
             print(f"Ошибка: {e} {response.text} {response.status_code}")


    def _get_order_items(self) -> List:
        """Возвращает список товаров заказа в зависимости от платформы."""
        if hasattr(self.order, 'items'):
            return list(self.order.items.all())
        return [self.order]  # Для платформ с одним товаром в заказе

    def _prepare_product_data(self, item, line_number: int) -> Dict:
        """Формирует данные по одному товару."""
        prod = item.product
        quantity = getattr(item, 'quantity', 1)
        price = getattr(item, 'price', self.order.price)
        amount = float(price) * int(quantity)
        nds_amount = amount * 5 / 105  # Расчет НДС 5%

        product_data = {
            "LineNumber": line_number,
            "ДатаОтгрузки": self._get_shipment_date(),
            "Номенклатура_Key": str(prod.uuid_1C) if prod else "00000000-0000-0000-0000-000000000000",
            "Количество": int(quantity),
            "КоличествоУпаковок": quantity,
            "Цена": float(price),
            "Сумма": amount,
            "СуммаНДС": 0,
            "СуммаСНДС": amount,
            "Отменено": False,
            "СрокПоставки": "0",
            "Содержание": "",
            "СтатусУказанияСерий": 0,
            "ВариантОбеспечения": "Отгрузить"
        }

        # Добавляем дефолтные значения
        product_data.update({
            k: v for k, v in self.DEFAULT_VALUES.items()
            if k not in product_data
        })

        return product_data

    def prepare_order_data(self) -> Dict:
        """Формирует полные данные заказа для 1С."""
        order_items = self._get_order_items()
        products_data = [
            self._prepare_product_data(item, i + 1)
            for i, item in enumerate(order_items)
        ]

        # Формируем комментарий
        comment = self._generate_order_comment(order_items)

        return {
            "Number": self.platform_info['number_1C'](self.order),
            "Date": self._get_current_datetime(),
            "Партнер_Key": str(self.order.id_patner),
            "Контрагент_Key": str(self.order.id_contr),
            "Организация_Key": "e57af50a-4c46-11ec-a9c8-f8cab8387a55",
            "Соглашение_Key": "d7009a1a-f768-11ee-8088-00155d46f78e",
            "Валюта_Key": "12fb735c-4c47-11ec-a9c8-f8cab8387a55",
            "СуммаДокумента": str(self.order.price),
            "ЦенаВключаетНДС": False,
            "ДатаСогласования": self._get_shipment_date(),
            "Согласован": True,
            "ДатаОтгрузки": self._get_shipment_date(),
            "НалогообложениеНДС": "ПродажаНеОблагаетсяНДС",
            "ХозяйственнаяОперация": "РеализацияКлиенту",
            "Назначение_Key": "6b48bbf4-3731-11f0-81cb-00155d46f78d",
            "Приоритет_Key": "12fb7386-4c47-11ec-a9c8-f8cab8387a55",
            "СкидкиРассчитаны": True,
            "МаксимальныйКодСтроки": "1",
            "Товары": products_data,
            "ЭтапыГрафикаОплаты": [],
            "СкидкиНаценки": [],
            "ДополнительныеРеквизиты": [],
            "Комментарий": comment,
            **{k: v for k, v in self.DEFAULT_VALUES.items() if k.startswith('Склад_Key')}
        }

    def _generate_order_comment(self, order_items: List) -> str:
        """Генерирует комментарий к заказу в зависимости от платформы."""
        if self.platform_info['name'] == 'Avito':
            adv_names = [
                item.name_advertisement_item
                for item in order_items
                if hasattr(item, 'name_advertisement_item')
            ]
            return f"{self.platform_info['name']}\n" + "\n".join(adv_names)

        number = getattr(self.order, self.platform_info['number_field'], "")
        return f"{self.platform_info['name']}\n{number}"

    def send_to_1c(self, post: bool = False) -> bool:
        """Отправляет заказ в 1С."""
        order_data = self.prepare_order_data()
        order_url = f"{self.BASE_URL}Document_ЗаказКлиента?$format=application/json;odata=nometadata"
        try:
            response = self._make_request(order_url, data=order_data)
            if response:
                self.order.exchange_1c = True
                self.order.save()
                post_url = f"{self.BASE_URL}Document_ЗаказКлиента(guid'{response['Ref_Key']}')/Post()"
                self._make_request(url=post_url)
            return True
        except requests.exceptions.RequestException as e:
            print(f'Error sending order to 1C: {str(e)}')
        return False