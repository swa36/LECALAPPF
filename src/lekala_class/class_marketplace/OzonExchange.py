import inspect
import json
from datetime import datetime
from pathlib import Path

from lekala_ppf.settings import OZON_ID, OZON_KEY
from src.lekala_class.class_marketplace.BaseMarketPlace import BaseMarketPlace
from order.models import MarketplaceControl


class OzonExchange(BaseMarketPlace):

    def __init__(self):
        self.headers = {
            'Client-Id': OZON_ID,
            'Api-Key': OZON_KEY
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
        return self._request('POST', 'v3/product/import', data=payload)

    def get_items(self, data=None):
        endpoint = 'v3/product/info/list'
        payload = {'offer_id': data}
        return self._request('POST', endpoint, data=payload)

    def update_remains(self, data=None, save_to_file=False):
        endpoint = 'v2/products/stocks'
        payload = {'stocks': data}
        if save_to_file:
            return self._save_payload_to_file(payload)
        return self._request('POST', endpoint, data=payload)

    def update_price(self, data=None, save_to_file=False):
        endpoint = 'v1/product/import/prices'
        payload = {'prices': data}
        if save_to_file:
            return self._save_payload_to_file(payload)
        return self._request('POST', endpoint, data=payload)

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

    def set_num_sku_id_ozon(self, info_ozon):
        for it in info_ozon['result']['items']:
            if it['sku'] != 0:
                try:
                    model = self.prod_in_catalog(it['offer_id'])
                    num = model.objects.get(offer_id=it['offer_id'])
                    print(f"{it['offer_id']} - {it['id']} - {num.name} - Ozon")
                    num.ozon_id = it['id']
                    num.ozon_sku = it['sku']
                    num.save()
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
        file_path = folder_path / f'{caller_name}_{timestamp}.json'

        # Сохраняем только payload
        with file_path.open('w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)

        return str(file_path)
