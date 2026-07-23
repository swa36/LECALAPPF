from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase

from aliexpress.models import AliData
from aliexpress.management.commands.reconcile_ali import Command
from catalog.models import Category, Product
from src.lekala_class.class_marketplace.AliExpress import AliExpress


class AliExpressReconciliationTests(TestCase):
    @patch('src.lekala_class.class_marketplace.BaseMarketPlace.requests.request')
    def test_request_timeout_is_reported_and_returns_failure(self, request):
        request.side_effect = requests.exceptions.Timeout('timed out')
        output = StringIO()

        with redirect_stdout(output):
            self.assertFalse(AliExpress().update_stock(data=[]))

        self.assertEqual(request.call_args.kwargs['timeout'], 30)
        self.assertIn('HTTP request failed', output.getvalue())
        self.assertIn('Timeout', output.getvalue())

    @patch('src.lekala_class.class_marketplace.BaseMarketPlace.time.sleep')
    @patch('src.lekala_class.class_marketplace.BaseMarketPlace.requests.request')
    def test_update_stock_retries_rate_limit_response(self, request, sleep):
        rate_limited = requests.Response()
        rate_limited.status_code = 429
        rate_limited.url = 'https://openapi.aliexpress.ru/api/v1/product/update-sku-stock'

        successful = requests.Response()
        successful.status_code = 200
        successful._content = b'{"data": {}}'
        successful.headers['Content-Type'] = 'application/json'
        request.side_effect = [rate_limited, successful]

        output = StringIO()
        with redirect_stdout(output):
            self.assertTrue(AliExpress().update_stock(data=[]))

        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(60.0)
        self.assertIn('HTTP 429', output.getvalue())

    @patch.object(AliExpress, '_request')
    def test_reads_all_ali_pages(self, request):
        request.side_effect = [{'data': [{'id': '1'}]}]

        self.assertEqual(AliExpress().get_all_products(), [{'id': '1'}])

    @patch.object(AliExpress, '_request', return_value=None)
    def test_delete_reports_api_failure(self, request):
        self.assertFalse(AliExpress().delete_products(['1']))

    @patch.object(AliExpress, '_request', return_value={'success': True})
    def test_delete_accepts_success_response_without_data(self, request):
        self.assertTrue(AliExpress().delete_products(['1']))

    @patch.object(AliExpress, '_request', return_value={'message': 'denied'})
    def test_delete_logs_rejected_api_response(self, request):
        output = StringIO()

        with redirect_stdout(output):
            self.assertFalse(AliExpress().delete_products(['1']))

        self.assertIn('AliExpress request rejected', output.getvalue())
        self.assertIn("'message': 'denied'", output.getvalue())

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

    @patch.object(AliExpress, '_request', return_value={'error': 'denied'})
    def test_product_mutations_reject_error_payloads(self, request):
        client = AliExpress()

        self.assertFalse(client.delete_products(['1']))
        self.assertFalse(client.update_stock(data=[]))
        self.assertFalse(client.set_online(['1']))

    @patch.object(AliExpress, '_request')
    def test_product_mutations_require_data_in_response(self, request):
        client = AliExpress()
        for response in ({}, {'message': 'denied'}):
            with self.subTest(response=response):
                request.return_value = response
                self.assertFalse(client.delete_products(['1']))
                self.assertFalse(client.update_stock(data=[]))
                self.assertFalse(client.set_online(['1']))

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
    def test_stock_updates_use_four_hundred_card_batches(self):
        self.assertEqual(Command.STOCK_BATCH_SIZE, 400)

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
    def test_dry_run_reports_that_no_changes_were_made(self, ali_cls):
        ali_cls.return_value.get_all_products.return_value = []
        output = StringIO()

        call_command('reconcile_ali', stdout=output)

        self.assertIn('Dry-run complete: no remote or local changes made.', output.getvalue())

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

    @patch('aliexpress.management.commands.reconcile_ali.AliExpress')
    def test_execute_reports_successful_deletion(self, ali_cls):
        ali_cls.return_value.get_all_products.return_value = [
            {'id': '100', 'sku': [{'code': 'MISSING'}]}
        ]
        ali_cls.return_value.delete_products.return_value = True
        output = StringIO()

        call_command('reconcile_ali', '--execute', stdout=output)

        self.assertIn('Starting execution', output.getvalue())
        self.assertIn('Delete batch 1/1 succeeded', output.getvalue())
        self.assertIn('Deleted AliExpress cards: 1', output.getvalue())

    @patch('aliexpress.management.commands.reconcile_ali.AliExpress')
    def test_execute_reports_failed_deletion(self, ali_cls):
        ali_cls.return_value.get_all_products.return_value = [
            {'id': '100', 'sku': [{'code': 'MISSING'}]}
        ]
        ali_cls.return_value.delete_products.return_value = False
        output = StringIO()

        call_command('reconcile_ali', '--execute', stdout=output)

        self.assertIn('Delete batch 1/1 failed', output.getvalue())
        self.assertIn('Failed delete batches: 1', output.getvalue())

    @patch('aliexpress.management.commands.reconcile_ali.AliExpress')
    def test_delete_error_payload_keeps_ali_link(self, ali_cls):
        AliData.objects.create(product=self.product, id_ali=100)
        ali_cls.return_value.get_all_products.return_value = [
            {'id': '100', 'sku': [{'code': 'MISSING'}]}
        ]
        ali_cls.return_value.delete_products.return_value = {'error': 'denied'}

        call_command('reconcile_ali', '--execute')

        self.assertTrue(AliData.objects.filter(product=self.product).exists())

    @patch('aliexpress.management.commands.reconcile_ali.AliExpress')
    def test_stock_error_payload_does_not_restore_offline_card(self, ali_cls):
        ali_cls.return_value.get_all_products.return_value = [
            {
                'id': '100',
                'sku': [{'code': self.product.code_1C}],
                'status': 'offline',
            }
        ]
        ali_cls.return_value.update_stock.return_value = {'error': 'denied'}

        call_command('reconcile_ali', '--execute')

        ali_cls.return_value.set_online.assert_not_called()
