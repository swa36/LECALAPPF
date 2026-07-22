from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from aliexpress.models import AliData
from catalog.models import Category, Product
from src.lekala_class.class_marketplace.AliExpress import AliExpress


class AliExpressReconciliationTests(TestCase):
    @patch.object(AliExpress, '_request')
    def test_reads_all_ali_pages(self, request):
        request.side_effect = [{'data': [{'id': '1'}]}]

        self.assertEqual(AliExpress().get_all_products(), [{'id': '1'}])

    @patch.object(AliExpress, '_request', return_value=None)
    def test_delete_reports_api_failure(self, request):
        self.assertFalse(AliExpress().delete_products(['1']))

    @patch.object(AliExpress, '_request')
    def test_reads_following_ali_page_after_full_page(self, request):
        first_page = [{'id': str(index)} for index in range(50)]
        request.side_effect = [
            {'data': first_page},
            {'data': [{'id': '50'}]},
        ]

        self.assertEqual(AliExpress().get_all_products(), first_page + [{'id': '50'}])
        self.assertEqual(
            request.call_args_list[1].kwargs['data']['last_product_id'], '49'
        )

    @patch.object(AliExpress, '_request', return_value={'data': []})
    def test_delete_sends_ids_in_twenty_item_batches(self, request):
        ids = [str(index) for index in range(21)]

        self.assertTrue(AliExpress().delete_products(ids))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[:2], ('POST', '/api/v1/product/delete'))
        self.assertEqual(request.call_args_list[0].kwargs['data'], {'productIds': ids[:20]})
        self.assertEqual(request.call_args_list[1].kwargs['data'], {'productIds': ids[20:]})

    @patch.object(AliExpress, '_request', return_value={'data': []})
    def test_set_online_sends_ids_to_online_endpoint(self, request):
        self.assertTrue(AliExpress().set_online(['1']))
        self.assertEqual(request.call_args.kwargs['data'], {'productIds': ['1']})
        self.assertEqual(request.call_args.args[:2], ('POST', '/api/v1/product/online'))

    @patch.object(AliExpress, '_request')
    def test_delete_ali_forwards_params_and_returns_api_response(self, request):
        response = {'data': {'deleted': ['1']}}
        request.return_value = response

        self.assertEqual(AliExpress().delete_ali(data=['1'], params={'x': 'y'}), response)
        request.assert_called_once_with(
            'POST',
            '/api/v1/product/offline',
            data={'productIds': ['1']},
            params={'x': 'y'},
        )


class ReconcileAliCommandTests(TestCase):
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

    @patch('aliexpress.management.commands.reconcile_ali.AliExpress')
    def test_dry_run_does_not_delete_stale_card(self, ali_cls):
        ali_cls.return_value.get_all_products.return_value = [
            {'id': '100', 'sku': [{'code': 'MISSING'}]}
        ]

        call_command('reconcile_ali', stdout=StringIO())

        ali_cls.return_value.delete_products.assert_not_called()

    @patch('aliexpress.management.commands.reconcile_ali.AliExpress')
    def test_execute_keeps_linked_duplicate(self, ali_cls):
        AliData.objects.create(product=self.product, id_ali=2)
        ali_cls.return_value.get_all_products.return_value = [
            {
                'id': '1',
                'sku': [{'code': self.product.code_1C}],
                'ali_created_at': '2026-01-01',
            },
            {
                'id': '2',
                'sku': [{'code': self.product.code_1C}],
                'ali_created_at': '2026-02-01',
            },
        ]
        ali_cls.return_value.delete_products.return_value = True

        call_command('reconcile_ali', '--execute')

        ali_cls.return_value.delete_products.assert_called_once_with(['1'])
