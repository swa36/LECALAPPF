from aliexpress.models import AliData
from src.lekala_class.class_marketplace.BaseMarketPlace import BaseMarketPlace
from django.conf import settings
from catalog.models import Product
import requests


class AliExpress(BaseMarketPlace):
    BASE_URL = 'https://openapi.aliexpress.ru/'

    def __init__(self):
        self.headers = {
            'x-auth-token': settings.ALI_KEY,
            'Content-Type': 'application/json',
        }
        super().__init__(headers=self.headers, base_url=self.BASE_URL)

    def get_item(self, params=None, data=None, save_to_file=False):
        endpoint = 'api/v1/scroll-short-product-by-filter'
        body = {
            "filter": {
                "search_content": {
                    "content_values": data,
                    "content_type": "SKU_SELLER_SKU"
                }
            },
            "limit": 50
        }
        if save_to_file:
            self._save_payload_to_file(body)
            return body
        return self._request("POST", endpoint, data=body, params=params)

    def update_stock(self, params=None, data=None, save_to_file=False):
        endpoint = 'api/v1/product/update-sku-stock'
        body = {"products": data}
        if save_to_file:
            self._save_payload_to_file(body)
            return body
        return self._request("POST", endpoint, data=body, params=params)

    def get_data_order(self, params=None, save_to_file=False):
        endpoint = 'seller-api/v1/order/get-order-list'
        body = {
            "order_statuses": [],
            "page_size": 50,
            "page": 1
        }
        if save_to_file:
            self._save_payload_to_file(body)
            return body
        return self._request("POST", endpoint, data=body, params=params)

    def get_order(self, params=None, save_to_file=False):
        endpoint = 'seller-api/v1/order/get-order-list'
        body = {
            "order_statuses": ["Created"],
            "page_size": 5,
            "page": 1
        }
        if save_to_file:
            self._save_payload_to_file(body)
            return
        return self._request("POST", endpoint, data=body, params=params)

    def delete_ali(self, params=None, data=None, save_to_file=False):
        endpoint = '/api/v1/product/offline'
        body = {"productIds": data}
        if save_to_file:
            self._save_payload_to_file(body)
            return body
        req = self._request("POST", endpoint, data=body, params=params)
        print(req)
        return req

    def set_id_ali(self, article, id_ali):
        try:
            product = Product.objects.get(code_1C=article)
            AliData.objects.update_or_create(product=product, id_ali=id_ali)
        except Exception as ex:
            print(f'❌ Ошибка для артикула {article}: {ex}')
            return id_ali
