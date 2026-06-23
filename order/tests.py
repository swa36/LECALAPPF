import json
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from catalog.models import Category, Product, TypePrices
from order.models import ItemInOrderOzon, OrderOzon


def fake_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.text = json.dumps(json_data, ensure_ascii=False)
    resp.json.return_value = json_data

    def raise_for_status():
        if status >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"{status}")

    resp.raise_for_status.side_effect = raise_for_status
    return resp


class OrderMarketplaceTo1CTest(TestCase):
    def setUp(self):
        TypePrices.objects.create(
            uuid_1C="e57af511-4c46-11ec-a9c8-f8cab8387a55",
            type_price="Розничная",
            suffix="retail_price",
        )
        category = Category.objects.create(
            uuid_1C="11111111-1111-1111-1111-111111111111",
            name="Категория",
        )
        self.product = Product.objects.create(
            uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d",
            main_img_uuid="f5a159fc-a7fb-11ef-8a72-00155d46f78d",
            article_1C="ART1",
            code_1C="CODE1",
            data_version="v1",
            name="Товар",
            description="Описание",
            stock=1,
            category=category,
        )
        self.order = OrderOzon.objects.create(
            number_ozon="123456789",
            price=1991,
        )
        ItemInOrderOzon.objects.create(
            order_num=self.order,
            content_type=ContentType.objects.get_for_model(Product),
            object_id=str(self.product.id),
            product=self.product,
            quantity=2,
            price=995.5,
        )

    def _client_class(self):
        from src.lekala_class.class_1C.ExchangeOrder1CtoMarket import (
            OrderMarketplaceTo1C,
        )

        return OrderMarketplaceTo1C

    @patch("src.lekala_class.class_1C.ExchangeOrder1CtoMarket.requests.post")
    def test_send_to_1c_posts_to_http_service_order_endpoint(self, post):
        post.return_value = fake_response(
            {"ref_key": "c4e6092a-6cd2-11f1-bbb7-08f97e612452"}
        )
        result = self._client_class()(self.order).send_to_1c()

        self.assertTrue(result)
        called_url = post.call_args[0][0]
        self.assertTrue(called_url.rstrip("/").endswith("/hs/prokopov/order"))

    @patch("src.lekala_class.class_1C.ExchangeOrder1CtoMarket.requests.post")
    def test_send_to_1c_sends_cyrillic_utf8_json_body(self, post):
        post.return_value = fake_response(
            {"ref_key": "c4e6092a-6cd2-11f1-bbb7-08f97e612452"}
        )
        self._client_class()(self.order).send_to_1c()

        _, kwargs = post.call_args
        self.assertNotIn("json", kwargs)
        body_bytes = kwargs["data"]
        self.assertIsInstance(body_bytes, bytes)
        self.assertIn("Покупатель".encode("utf-8"), body_bytes)
        self.assertIn("Товары".encode("utf-8"), body_bytes)
        self.assertEqual(
            kwargs["headers"]["Content-Type"],
            "application/json; charset=utf-8",
        )

    @patch("src.lekala_class.class_1C.ExchangeOrder1CtoMarket.requests.post")
    def test_send_to_1c_builds_minimal_order_items(self, post):
        post.return_value = fake_response(
            {"ref_key": "c4e6092a-6cd2-11f1-bbb7-08f97e612452"}
        )
        self._client_class()(self.order).send_to_1c()

        body = json.loads(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(body["Покупатель"], "OZON 123456789")
        self.assertEqual(body["Номер"], "OZ00-123456789")
        self.assertEqual(body["Комментарий"], "OZON\n123456789")
        self.assertEqual(body["СуммаДокумента"], 1991)
        self.assertEqual(
            body["Товары"],
            [
                {
                    "Номенклатура_Key": str(self.product.uuid_1C),
                    "Количество": 2,
                    "Цена": 995.5,
                }
            ],
        )

    @patch("src.lekala_class.class_1C.ExchangeOrder1CtoMarket.requests.post")
    def test_successful_ref_key_marks_order_as_exchanged(self, post):
        post.return_value = fake_response(
            {"ref_key": "c4e6092a-6cd2-11f1-bbb7-08f97e612452"}
        )

        result = self._client_class()(self.order).send_to_1c()

        self.assertTrue(result)
        self.order.refresh_from_db()
        self.assertTrue(self.order.exchange_1c)

    @patch("src.lekala_class.class_1C.ExchangeOrder1CtoMarket.requests.post")
    def test_error_response_returns_false_and_does_not_post_document(self, post):
        post.return_value = fake_response(
            {"error": "Не указаны товары заказа", "code": "MISSING_ITEMS"},
            status=400,
        )

        result = self._client_class()(self.order).send_to_1c()

        self.assertFalse(result)
        self.order.refresh_from_db()
        self.assertFalse(self.order.exchange_1c)
        urls = [call.args[0] for call in post.call_args_list]
        self.assertEqual(len(urls), 1)
        self.assertFalse(any("/Post()" in url for url in urls))
