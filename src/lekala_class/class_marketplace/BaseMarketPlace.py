import inspect
import json
from  abc import ABC
from datetime import datetime
from pathlib import Path
from ozon.models import OzonData
from order.models import *
import requests

class BaseMarketPlace(ABC):
    def __init__(self, headers, base_url):
        self.headers = headers
        self.base_url = base_url

    def _request(self, method, endpoint, data=None, params=None, use_json=True, extra_headers=None):
        """
        :param method: HTTP метод (GET, POST и т.д.)
        :param endpoint: путь к API
        :param data: тело запроса (dict)
        :param params: параметры в URL (dict)
        :param use_json: если False — передаётся как form-urlencoded (data), иначе — json
        :param extra_headers: дополнительные заголовки (например, Authorization)
        """
        url = self.base_url + endpoint
        headers = self.headers.copy()
        if extra_headers:
            headers.update(extra_headers)

        request_kwargs = {
            'method': method,
            'url': url,
            'headers': headers,
            'params': params
        }
        if data:
            if use_json:
                request_kwargs['json'] = data
            else:
                request_kwargs['data'] = data

        try:
            response = requests.request(**request_kwargs)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"❌ HTTP error for {method} {url}")
            print(f"Status code: {response.status_code}")
            print(f"Response text: {response.text}") # если нужно, можешь убрать или заменить на return None
        if response.status_code == 204:
            print(f"204 No Content: {url}")
            return None
        return response.json()

    def _get_model_by_class_name(self):
        name = self.__class__.__name__.lower()  # например: ozonmarketplace
        if 'OzonExchange'.lower() in name:
            return OzonData
        elif 'wb'.lower() in name:
            from wildberries.models import WBData
            return WBData
        else:
            raise NotImplementedError(f"Модель не определена для класса: {self.__class__.__name__}")

    def prod_in_catalog(self, id):
        model = self._get_model_by_class_name()
        num = model.objects.get(offer_id=id)
        return num.product

    def number_to_1c(self):
        name = self.__class__.__name__.lower()
        number = None
        if 'OzonExchange'.lower() in name:
            number = OrderOzon.objects.last().number_1C if OrderOzon.objects.last() else "OZ00-000000"
        elif 'GetOrderWB'.lower() in name:
            number = OrderWB.objects.last().number_1C if OrderWB.objects.last() else "WB00-000000"
        elif 'YaMarket'.lower() in name:
            number = OrderYM.objects.last().number_1C if OrderWB.objects.last() else "YA00-000000"
        elif 'AliExpress'.lower() in name:
            number = OrderAli.objects.last().number_1C if OrderWB.objects.last() else "AL00-000000"
        if number:
            mask = '000000'
            n = number.split('-')
            min_mask = mask[:-len(str(int(n[1]) + 1))]
            n[1] = min_mask + str(int(n[1]) + 1)
            num = '-'.join(n)
            return num

    def round_to_nearest_10_custom(self, n):
        remainder = n % 10
        if remainder >= 5:
            return int(n - remainder + 10)
        else:
            return int(n - remainder)

    def _save_payload_to_file(self, payload):
        # Имя вызывающего метода
        caller_name = inspect.stack()[1].function

        # Путь к папке на основе имени метода
        folder_path = Path(f'json/request/{self.__class__.__name__}/{caller_name}')
        folder_path.mkdir(parents=True, exist_ok=True)

        # Уникальное имя файла по времени
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        file_path = folder_path / f'{caller_name}_{timestamp}.json'

        # Сохраняем только payload
        with file_path.open('w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)

        return str(file_path)



