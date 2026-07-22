import logging

from django.core.cache import cache
from src.lekala_class.class_marketplace.BaseMarketPlace import BaseMarketPlace
from django.conf import settings


logger = logging.getLogger(__name__)


class AvitoExchange(BaseMarketPlace):
    REDIS_TOKEN_KEY = 'avito_access_token'

    def __init__(self):
        self.client_id = settings.AVITO_ID
        self.client_secret = settings.AVITO_KEY
        super().__init__(headers={}, base_url='https://api.avito.ru')

    def get_token(self):
        token = cache.get(self.REDIS_TOKEN_KEY)
        if token:
            return token

        endpoint = '/token/'
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = self._request('POST', endpoint, data=data, use_json=False, extra_headers=headers)
        token = response['access_token']

        # Avito обычно даёт токен на 1 час → TTL 50 минут
        cache.set(self.REDIS_TOKEN_KEY, token, timeout=60 * 50)
        return token

    def get_order(self, save_to_file=False):
        try:
            token = self.get_token()
            response = self._request(
                'GET',
                '/order-management/1/orders',
                params={'statuses': 'on_confirmation'},
                extra_headers={'Authorization': f'Bearer {token}'},
            )
        except Exception:
            logger.exception('Avito orders request failed')
            return {'orders': []}

        if save_to_file:
            self._save_payload_to_file(response)
        return response or {'orders': []}
