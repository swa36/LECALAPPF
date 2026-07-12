from unittest.mock import patch
import uuid

from django.test import TestCase
from catalog.models import Product
from ozon.models import OzonData


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


def make_ozon_product(code):
    """Товар + запись OzonData с offer_id=code."""
    product = Product.objects.create(
        uuid_1C=uuid.uuid4(),
        article_1C=code,
        code_1C=code,
        data_version="v1",
        name=f"Товар {code}",
        description="",
        stock=5,
    )
    OzonData.objects.create(product=product, offer_id=code)
    return product


def page(items, last_id=""):
    """Ответ /v3/product/list с одной страницей."""
    return {"result": {"items": items, "last_id": last_id, "total": len(items)}}


class CloseUnknownOzonStocksTest(TestCase):
    def _run(self, mock_api_cls, dry_run=False):
        from ozon.tasks import close_unknown_ozon_stocks
        with patch("ozon.tasks.time.sleep"):
            return close_unknown_ozon_stocks(dry_run=dry_run)

    @patch("ozon.tasks.OzonExchange")
    def test_zeroes_only_unknown_offer_ids(self, mock_api_cls):
        make_ozon_product("KNOWN-1")
        api = mock_api_cls.return_value
        api.get_product_list.return_value = page([
            {"offer_id": "KNOWN-1", "product_id": 1, "archived": False},
            {"offer_id": "UNKNOWN-1", "product_id": 2, "archived": False},
        ])
        api.update_remains.return_value = {"result": []}

        result = self._run(mock_api_cls)

        self.assertEqual(result, ["UNKNOWN-1"])
        api.update_remains.assert_called_once_with(data=[{
            "offer_id": "UNKNOWN-1",
            "stock": 0,
            "warehouse_id": 22865154657000,
            "quant_size": 1,
        }])

    @patch("ozon.tasks.OzonExchange")
    def test_pagination_and_archived_skipped(self, mock_api_cls):
        api = mock_api_cls.return_value
        api.get_product_list.side_effect = [
            page([{"offer_id": "A-1", "product_id": 1, "archived": False}], last_id="next"),
            page([
                {"offer_id": "A-2", "product_id": 2, "archived": True},
                {"offer_id": "A-3", "product_id": 3, "archived": False},
            ]),
        ]
        api.update_remains.return_value = {"result": []}

        result = self._run(mock_api_cls)

        self.assertEqual(result, ["A-1", "A-3"])
        self.assertEqual(api.get_product_list.call_count, 2)

    @patch("ozon.tasks.OzonExchange")
    def test_batching_by_100(self, mock_api_cls):
        api = mock_api_cls.return_value
        items = [
            {"offer_id": f"U-{i:03d}", "product_id": i, "archived": False}
            for i in range(250)
        ]
        api.get_product_list.return_value = page(items)
        api.update_remains.return_value = {"result": []}

        result = self._run(mock_api_cls)

        self.assertEqual(len(result), 250)
        self.assertEqual(api.update_remains.call_count, 3)
        sizes = [len(c.kwargs["data"]) for c in api.update_remains.call_args_list]
        self.assertEqual(sizes, [100, 100, 50])
        for call in api.update_remains.call_args_list:
            for item in call.kwargs["data"]:
                self.assertEqual(item["stock"], 0)

    @patch("ozon.tasks.OzonExchange")
    def test_dry_run_sends_nothing(self, mock_api_cls):
        api = mock_api_cls.return_value
        api.get_product_list.return_value = page(
            [{"offer_id": "UNKNOWN-1", "product_id": 1, "archived": False}]
        )

        result = self._run(mock_api_cls, dry_run=True)

        self.assertEqual(result, ["UNKNOWN-1"])
        api.update_remains.assert_not_called()

    @patch("ozon.tasks.OzonExchange")
    def test_page_error_aborts_without_sending(self, mock_api_cls):
        api = mock_api_cls.return_value
        api.get_product_list.side_effect = Exception("ozon down")

        result = self._run(mock_api_cls)

        self.assertEqual(result, [])
        api.update_remains.assert_not_called()

    @patch("ozon.tasks.OzonExchange")
    def test_invalid_later_page_aborts_without_sending(self, mock_api_cls):
        api = mock_api_cls.return_value
        api.get_product_list.side_effect = [
            page([{"offer_id": "UNKNOWN-1", "product_id": 1, "archived": False}], last_id="next"),
            {"code": 7, "message": "ozon down"},
        ]

        result = self._run(mock_api_cls)

        self.assertEqual(result, [])
        api.update_remains.assert_not_called()


class UpdateRemainsOzonIntegrationTest(TestCase):
    @patch("ozon.tasks.close_unknown_ozon_stocks")
    @patch("ozon.tasks.OzonExchange")
    def test_calls_close_unknown_after_own_stocks(self, mock_api_cls, mock_close):
        from ozon.tasks import update_remains_ozon

        update_remains_ozon()

        mock_close.assert_called_once_with()

    @patch("ozon.tasks.close_unknown_ozon_stocks", side_effect=Exception("boom"))
    @patch("ozon.tasks.OzonExchange")
    def test_close_unknown_error_does_not_break_task(self, mock_api_cls, mock_close):
        from ozon.tasks import update_remains_ozon

        update_remains_ozon()  # не должно выбросить исключение

        mock_close.assert_called_once_with()
