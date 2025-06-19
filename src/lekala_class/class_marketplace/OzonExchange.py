import inspect
import json
from datetime import datetime
from pathlib import Path

from catalog.models import Product
from lekala_ppf.settings import OZON_ID, OZON_KEY
from ozon.models import OzonData
from src.lekala_class.class_marketplace.BaseMarketPlace import BaseMarketPlace
from order.models import MarketplaceControl


class OzonExchange(BaseMarketPlace):

    def __init__(self):
        self.headers = {
            'Client-Id': OZON_ID,
            'Api-Key': OZON_KEY,
            'Content-Type': 'application/json'
        }
        self.base_url = 'https://api-seller.ozon.ru/'
        super().__init__(self.headers, self.base_url)

    def get_img_ozon(self, data):
        endpoint = 'v2/product/pictures/info'
        payload = {
            "product_id": data
        }
        return self._request('POST', endpoint, data=payload)

    def post_items(self, data=None, save_to_file=False):
        payload = {'items': data}
        if save_to_file:
            return self._save_payload_to_file(payload)
        res =  self._request('POST', 'v3/product/import', data=payload)
        print(res)
        return res

    def get_items(self, data=None):
        endpoint = 'v3/product/info/list'
        payload = {'offer_id': data}
        res = self._request('POST', endpoint, data=payload)
        # print(res)
        return res

    def update_remains(self, data=None, save_to_file=False):
        endpoint = 'v2/products/stocks'
        payload = {'stocks': data}
        if save_to_file:
            return self._save_payload_to_file(payload)
        response = self._request('POST', endpoint, data=payload)
        # print(response)
        return response

    def update_price(self, data=None, save_to_file=False):
        endpoint = 'v1/product/import/prices'
        payload = {'prices': data}
        if save_to_file:
            return self._save_payload_to_file(payload)
        response = self._request('POST', endpoint, data=payload)
        print(response)
        return response

    def update_article(self, data=None):
        endpoint = 'v1/product/update/offer-id'
        payload = {"update_offer_id": data}
        return self._request('POST', endpoint, data=payload)

    def get_new_order(self, num_order=None):
        endpoint = 'v3/posting/fbs/get'
        payload = {
            "posting_number": num_order,
            "with": {
                "analytics_data": False,
                "barcodes": False,
                "financial_data": False,
                "product_exemplars": False,
                "translit": False
            }
        }
        return self._request('POST', endpoint, data=payload)

    def post_update_attr(self, data=None, save_to_file=False):
        endpoint = 'v1/product/attributes/update'
        payload = {"items": data}
        if save_to_file:
            self._save_payload_to_file(payload)
            return
        return self._request('POST', endpoint, data=payload)


    def post_new_img(self, data=None, save_to_file=False):
        endpoint = 'v1/product/pictures/import'
        if save_to_file:
            self._save_payload_to_file(data)
            return
        req = self._request('POST', endpoint, data=data)
        print(req)
        return req


    def set_num_sku_id_ozon(self, info_ozon):
        for it in info_ozon['items']:
            if it['id']:
                try:
                    num = Product.objects.get(code_1C=it['offer_id'])
                    OzonData.objects.update_or_create(
                        offer_id=it['offer_id'],
                        product=num,
                        defaults={
                            'ozon_id':it['id'],
                            'ozon_sku':it['barcodes'][0] if it['barcodes'] else None
                        }
                    )
                    print(f"{it['offer_id']} - {it['id']} - {num.name} - Ozon")
                except Exception as ex:
                    print(it['offer_id'])


    def work_time_ozon(self):
        work_ozon = MarketplaceControl.objects.get(name='ozon')
        return work_ozon.is_available_now()

    def _save_payload_to_file(self, payload):
        # Имя вызывающего метода
        caller_name = inspect.stack()[1].function

        # Путь к папке на основе имени метода
        folder_path = Path(f'json/ozon_request/{caller_name}')
        folder_path.mkdir(parents=True, exist_ok=True)

        # Уникальное имя файла по времени
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        file_path = folder_path / f'{caller_name}_{timestamp}.txt'

        # Сохраняем только payload
        with file_path.open('w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)

        return str(file_path)
