from unittest.mock import patch

from django.test import TestCase


class GetProductListTest(TestCase):
    @patch("src.lekala_class.class_marketplace.OzonExchange.OzonExchange._request")
    def test_get_product_list_calls_v3_product_list(self, mock_request):
        from src.lekala_class.class_marketplace.OzonExchange import OzonExchange

        mock_request.return_value = {"result": {"items": [], "last_id": "", "total": 0}}
        api = OzonExchange()
        res = api.get_product_list(last_id="abc", limit=500)

        mock_request.assert_called_once_with(
            "POST",
            "v3/product/list",
            data={
                "filter": {"visibility": "ALL"},
                "last_id": "abc",
                "limit": 500,
            },
        )
        self.assertEqual(res, {"result": {"items": [], "last_id": "", "total": 0}})
