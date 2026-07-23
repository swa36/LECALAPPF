from django.test import TestCase
from unittest.mock import patch

from catalog.models import Category, Product
from order.models import OrderAvito
from src.lekala_class.class_marketplace.Avito import AvitoExchange
from avito.tasks import getOrderAvito


class AvitoExchangeTests(TestCase):
    @patch.object(AvitoExchange, 'get_token', side_effect=Exception('auth failed'))
    def test_get_order_returns_empty_after_token_failure(self, token):
        self.assertEqual(AvitoExchange().get_order(), {'orders': []})

    @patch.object(AvitoExchange, 'get_token', return_value='token')
    @patch.object(AvitoExchange, '_request', side_effect=Exception('network failed'))
    def test_get_order_returns_empty_after_request_failure(self, request, token):
        self.assertEqual(AvitoExchange().get_order(), {'orders': []})


class AvitoOrderImportTests(TestCase):
    def setUp(self):
        category = Category.objects.create(
            uuid_1C='11111111-1111-1111-1111-111111111111', name='Category'
        )
        self.product = Product.objects.create(
            uuid_1C='22222222-2222-2222-2222-222222222222',
            main_img_uuid='33333333-3333-3333-3333-333333333333',
            article_1C='ARTICLE',
            code_1C='CODE',
            data_version='v1',
            name='Product',
            description='Description',
            stock=1,
            category=category,
        )

    @patch('avito.tasks.AvitoExchange.get_order')
    def test_import_saves_avito_item_total_as_price(self, get_order):
        get_order.return_value = {'orders': [{'marketplaceId': 'A-1', 'prices': {'total': 900}, 'items': [
            {'id': self.product.code_1C, 'title': 'Ad', 'count': 2, 'prices': {'total': 1000}},
        ]}]}

        result = getOrderAvito()

        order = OrderAvito.objects.get(number_avito='A-1')
        self.assertEqual(result, {'created': 1})
        self.assertEqual(order.number_1C, 'AV00-000001')
        self.assertEqual(order.price, 900)
        item = order.items.get()
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.price, 1000)
        self.assertEqual(item.total_price, 1000)

    @patch('avito.tasks.AvitoExchange.get_order')
    def test_import_saves_advertisement_title_on_order(self, get_order):
        get_order.return_value = {'orders': [{'marketplaceId': 'A-title', 'items': [
            {'id': self.product.code_1C, 'title': 'Название из Avito', 'prices': {'total': 1000}},
        ]}]}

        getOrderAvito()

        self.assertEqual(
            OrderAvito.objects.get(number_avito='A-title').name_advertisement,
            'Название из Avito',
        )

    @patch('avito.tasks.AvitoExchange.get_order')
    def test_import_keeps_unknown_item_and_skips_duplicate(self, get_order):
        get_order.return_value = {'orders': [{'marketplaceId': 'A-2', 'items': [
            {'id': 'UNKNOWN', 'title': 'Unknown ad', 'prices': {'price': 300}},
        ]}]}

        getOrderAvito()
        result = getOrderAvito()

        self.assertEqual(result, {'created': 0})
        self.assertEqual(OrderAvito.objects.filter(number_avito='A-2').count(), 1)
        self.assertIsNone(OrderAvito.objects.get().items.get().product)
