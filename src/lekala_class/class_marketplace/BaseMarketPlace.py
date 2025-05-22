from  abc import ABC
from itertools import product

from PIL.ImImagePlugin import number

from ozon.models import OzonData
from order.models import *
import requests

class BaseMarketPlace(ABC):
    def __init__(self, headers, base_url):
        self.headers = headers
        self.base_url = base_url


    def _request(self, method, endpoint, data=None, params=None):
        url = self.base_url + endpoint
        response = requests.request(method, url, headers=self.headers, json=data, params=params)
        response.raise_for_status()
        return response.json()

    def _get_model_by_class_name(self):
        name = self.__class__.__name__.lower()  # например: ozonmarketplace
        if 'OzonExchange'.lower() in name:
            return OzonData
        # elif 'wb'.lower() in name:
        #     from wildberries.models import WBData
        #     return WBData
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
        if number:
            mask = '000000'
            n = number.split('-')
            min_mask = mask[:-len(str(int(n[1]) + 1))]
            n[1] = min_mask + str(int(n[1]) + 1)
            num = '-'.join(n)
            return num




