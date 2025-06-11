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

    def post_items(self, data, save_to_file=True):
        endpoint = 'v2/cards/upload'
        if save_to_file:
            self._save_payload_to_file(data)
            return
        req = self._request("POST", endpoint, data)
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

    def post_img(self, item, link):
        url = self.BASE_URL + 'v3/media/file'
        header = self.headers.copy()
        header['X-Nm-Id'] = str(item.id_wb)
        print(f'WB {item.name} {item.id_wb} {item.items_id_wb} {item.barcode_wb}')
        all_image = item.image.all().order_by('-main')
        photo_num = 1
        original_width, original_height = 700, 900
        photo_name = 0
        if link:
            data_item_img = {
                "nmId": int(header['X-Nm-Id']),
                "data": []
            }
        for img in all_image:
            if img.main:
                path_img = settings.BASE_DIR + url
            else:
                path_img = img.images.path
            img_pil = Image.open(path_img)
            width, height = img_pil.size
            w, h = 0, 0
            if width < original_width:
                w = original_width - width
            if height < original_height:
                h = original_height - height
            new_size = None
            if w != 0 and h != 0:
                new_size = (width + w, height + h)
            elif w != 0:
                new_size = (width + w, height + w)
            elif h != 0:
                new_size = (width + h, height + h)
            if new_size:
                new_img = img_pil.resize(new_size)
                try:
                    path = f"media/WB/{item.id}/"
                    os.mkdir(path)
                    os.chown(path, 0, 1001)
                    os.chmod(path, 0o770)
                except FileExistsError:
                    path
                path_img = f'{path}{photo_num}.jpg'
                new_img.save(path_img)
                photo_name += 1
                header['X-Photo-Number'] = str(photo_num)
                if link:
                    url = 'http://lpff.ru'
                    data_item_img['data'].append(f'{url}{path_img}')
            else:
                header['X-Photo-Number'] = str(photo_num)
                if link:
                    url = 'http://lpff.ru'
                    data_item_img['data'].append(f'{url}{img.images.url}')
            if not link:
                req = requests.post(url=url, headers=header, files={'uploadfile': open(path_img, 'rb')})
                print(req.json())
                photo_num += 1
                time.sleep(1)
        if link:
            self.post_img_link(data=data_item_img)
        return

    def post_img_link(self, data=None, params=None):
        endpoint = 'v3/media/save'
        print(data)
        req = self._request("POST", endpoint, params, data)
        print(req)
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