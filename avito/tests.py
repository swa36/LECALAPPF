from django.test import TestCase
from unittest.mock import patch

from src.lekala_class.class_marketplace.Avito import AvitoExchange


class AvitoExchangeTests(TestCase):
    @patch.object(AvitoExchange, 'get_token', side_effect=Exception('auth failed'))
    def test_get_order_returns_empty_after_token_failure(self, token):
        self.assertEqual(AvitoExchange().get_order(), {'orders': []})

    @patch.object(AvitoExchange, 'get_token', return_value='token')
    @patch.object(AvitoExchange, '_request', side_effect=Exception('network failed'))
    def test_get_order_returns_empty_after_request_failure(self, request, token):
        self.assertEqual(AvitoExchange().get_order(), {'orders': []})
