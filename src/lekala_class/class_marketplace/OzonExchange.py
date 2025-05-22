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

    def post_items(self, data=None):
        endpoint = 'v3/product/import'
        payload = {'items': data}
        return self._request('POST', endpoint, data=payload)

    def get_items(self, data=None):
        endpoint = 'v3/product/info/list'
        payload = {'offer_id': data}
        return self._request('POST', endpoint, data=payload)

    def update_remains(self, data=None):
        endpoint = 'v2/products/stocks'
        payload = {'stocks': data}
        return self._request('POST', endpoint, data=payload)

    def update_price(self, data=None):
        endpoint = 'v1/product/import/prices'
        payload = {'prices': data}
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
