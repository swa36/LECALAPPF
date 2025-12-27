import json
from datetime import time
from django.conf import settings

from catalog.models import Product
from src.lekala_class.class_marketplace.BaseMarketPlace import BaseMarketPlace
from PIL import Image
import os, requests, time, datetime
from order.models import MarketplaceControl
from wildberries.models import WBData


class WBItemCard(BaseMarketPlace):
    BASE_URL = 'https://content-api.wildberries.ru/content/'

    def __init__(self, **kwargs):
        self.headers = {
            'Authorization': settings.WB_KEY
        }
        super().__init__(self.headers, self.BASE_URL,)

    def post_items(self, data, save_to_file=False):
        endpoint = 'v2/cards/upload'
        if save_to_file:
            self._save_payload_to_file(data)
            return
        req = self._request("POST", endpoint, data)
        print(req)
        return req

    def update_item(self, data, save_to_file=False):
        endpoint = 'v2/cards/update'
        if save_to_file:
            self._save_payload_to_file(data)
            return
        req = self._request("POST", endpoint, data)
        print(req)
        return req



    def del_item(self, data=None):
        endpoint = 'v2/cards/delete/trash'
        body = {"nmIDs": data}
        return self._request("POST", endpoint, body)

    def get_items(self, param='all', cursor=None):
        parameters = {
            'all': -1,
            'withoutImg': 0,
            'withImg': 1
        }
        endpoint = 'v2/get/cards/list'
        if cursor:
            cursor_data = cursor
        else:
            cursor_data = {
                "limit": 100
            }
        data = {
            "settings": {
                "sort": {
                    "ascending": False
                },
                "filter": {
                    "textSearch": "",
                    "withPhoto": parameters[param]
                },
                "cursor": cursor_data
            }
        }
        req = self._request("POST", endpoint, data)
        return req

    def set_id_wb_num(self, data):
        for i in data['cards']:
            try:
                prod = Product.objects.get(article_1C=i['vendorCode'])
                print(f'WB {i["imtID"]} {i["sizes"][0]["skus"][0]} {prod.name}')
                WBData.objects.update_or_create(
                    product=prod,
                    defaults={
                        'offer_id':i['vendorCode'],
                        'wb_id':i['nmID'],
                        'wb_barcode':i['sizes'][0]['skus'][0],
                        'wb_item_id':i['imtID']
                    }
                )
            except:
                print(i['vendorCode'])

    def post_img(self, item):
        url = 'https://lpff.ru'
        print(f'WB {item.name} {item.wb.wb_id} {item.wb.wb_item_id} {item.wb.wb_barcode}')
        all_image = item.images.all().order_by('-main')
        family = item.category.get_family()
        video_category = family.filter(video_instruction_url__isnull=False).first()
        # photo_num = 1
        # original_width, original_height = 700, 900
        # photo_name = 0
        data_item_img = {
            "nmId": item.wb.wb_id,
            "data": []
        }
        if all_image:
            for img in all_image:
                data_item_img['data'].append(f'{url}{img.image.url}')

            if video_category:
                data_item_img['data'].append(f'{url}/{video_category.file}')
        self.post_img_link(data=json.dumps(data_item_img, ensure_ascii=False))
        time.sleep(5)
        return


    def post_img_link(self, data=None, params=None, save_to_file=False):
        endpoint = 'v3/media/save'
        print(data)
        if save_to_file:
            self._save_payload_to_file(data)
            return
        req = requests.post(self.BASE_URL+endpoint, data=data, headers={
            'Content-Type':'application/json',
            'Authorization':settings.WB_KEY
        })
        print(req.json())
        if req.status_code == 429:
            print('Шлем повтор')
            self.post_img_link(self, data, params, save_to_file)
        return req


class StockItemWB(BaseMarketPlace):
    BASE_URL = 'https://marketplace-api.wildberries.ru/api/'

    def __init__(self, **kwargs):
        self.headers = {
            'Authorization': settings.WB_KEY
        }
        super().__init__(self.headers, self.BASE_URL,)

    def update_remains(self, data=None, save_to_file=False):
        endpoint = 'v3/stocks/178002'
        body = {"stocks": data}
        if save_to_file:
            return self._save_payload_to_file(body)
        req = self._request("PUT", endpoint, body)
        return req

    def del_stock_item(self, data=None):
        endpoint = 'v3/stocks/178002'
        body = {"skus": data}
        delete = requests.delete(self.BASE_URL + endpoint, json=body)
        print(delete.text)
        return

    def work_time_wb(self):
        work_wb = MarketplaceControl.objects.get(name='wb')
        return work_wb.is_available_now()


class PriceItemWB(BaseMarketPlace):
    BASE_URL = 'https://discounts-prices-api.wildberries.ru/api/'

    def __init__(self, **kwargs):
        self.headers = {
            'Authorization': settings.WB_KEY
        }
        super().__init__(self.headers, self.BASE_URL,)

    def update_price(self, data=None, save_to_file=False):
        endpoint = 'v2/upload/task'
        body = {"data": data}
        if save_to_file:
            return self._save_payload_to_file(body)
        post = requests.post(
            url=self.BASE_URL + endpoint,
            headers=self.headers,
            json=body
        )
        print(post.json())
        return post
        # return self._make_request("POST", endpoint, params, body)

    def set_price_club_wb(self, data=None, save_to_file=False):
        endpoint = 'v2/upload/task/club-discount'
        body = {"data": data}
        if save_to_file:
            return self._save_payload_to_file(body)
        post = requests.post(
            url=self.BASE_URL + endpoint,
            headers=self.headers,
            json=body
        )
        print(post.json())
        return post


class GetOrderWB(BaseMarketPlace):
    BASE_URL = 'https://marketplace-api.wildberries.ru/api/'

    def __init__(self, **kwargs):
        self.headers = {
            'Authorization': settings.WB_KEY
        }
        super().__init__(self.headers, self.BASE_URL,)

    def get_new_order(self):
        endpoint = 'v3/orders/new'
        return self._request("GET", endpoint)
