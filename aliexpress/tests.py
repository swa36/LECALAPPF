from django.test import TestCase
from unittest.mock import patch

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
        self.assertEqual(request.call_args_list[0].kwargs['data'], {'productIds': ids[:20]})
        self.assertEqual(request.call_args_list[1].kwargs['data'], {'productIds': ids[20:]})

    @patch.object(AliExpress, '_request', return_value={'data': []})
    def test_set_online_sends_ids_to_online_endpoint(self, request):
        self.assertTrue(AliExpress().set_online(['1']))
        self.assertEqual(request.call_args.kwargs['data'], {'productIds': ['1']})
        self.assertEqual(request.call_args.args[:2], ('POST', '/api/v1/product/online'))
