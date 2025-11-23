from django.conf import settings
from src.lekala_class.class_marketplace.BaseMarketPlace import BaseMarketPlace


class YaMarketApi(BaseMarketPlace):
    def __init__(self):
        super().__init__(
            headers={'Api-Key': settings.YA_KEY},
            base_url='https://api.partner.market.yandex.ru/'
        )
        self.business_id = 82821173
        self.campaign_id = 70648764

    def post_new_item(self, data, save_to_file=False):
        endpoint = f'businesses/{self.business_id}/offer-mappings/update'
        payload = {
            "offerMappings": data,
            "onlyPartnerMediaContent": False
        }
        if save_to_file:
            self._save_payload_to_file(payload)
            return payload
        req = self._request('POST', endpoint, data=payload)
        print(req)
        return req

    def sent_stock(self, data, save_to_file=False):
        endpoint = f'campaigns/{self.campaign_id}/offers/stocks'
        payload = {"skus": data}
        if save_to_file:
            self._save_payload_to_file(payload)
            return payload
        return self._request('PUT', endpoint, data=payload)

    def update_nds_offers(self, data, save_to_file=False):
        endpoint = f'campaigns/{self.campaign_id}/offers/update'
        payload = {"offers": data}
        if save_to_file:
            self._save_payload_to_file(payload)
            return payload
        return self._request('POST', endpoint, data=payload)

    def get_order_info(self, order_id, save_to_file=False):
        endpoint = f'campaigns/{self.campaign_id}/orders/{order_id}'
        return self._request('GET', endpoint)

