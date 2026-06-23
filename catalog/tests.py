import base64
from unittest.mock import MagicMock, patch

from django.conf import settings as dj_settings
from django.test import TestCase, override_settings

from catalog.models import (
    Category,
    NameAdditionalAttributes,
    Prices,
    Product,
    TypePrices,
    ValueAdditionalAttributes,
)
from src.lekala_class.class_1C.ExChange1C import ExChange1C
from src.lekala_class.class_1C.GetData1C import GetData1C


def fake_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = json_data

    def raise_for_status():
        if status >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"{status}")

    resp.raise_for_status.side_effect = raise_for_status
    return resp


ONE_PX_PNG = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
).decode()


class ExChange1CHttpClientTest(TestCase):
    def setUp(self):
        self.client = ExChange1C()

    def test_base_url_points_to_http_service(self):
        self.assertTrue(self.client.BASE_URL.rstrip("/").endswith("/hs/prokopov"))

    def test_make_request_builds_url_and_sends_gzip_header(self):
        with patch.object(self.client.session, "request") as req:
            req.return_value = fake_response({"value": []})
            self.client._make_request("GET", "categories")
        args, kwargs = req.call_args
        called_url = kwargs.get("url") or args[1]
        self.assertTrue(called_url.endswith("/hs/prokopov/categories"))
        headers = {**self.client.session.headers, **(kwargs.get("headers") or {})}
        self.assertIn("gzip", headers.get("Accept-Encoding", "").lower())
        self.assertIsNotNone(kwargs.get("auth"))

    def test_make_request_returns_parsed_json(self):
        with patch.object(self.client.session, "request") as req:
            req.return_value = fake_response({"value": [{"ref_key": "a"}]})
            data = self.client._make_request("GET", "categories")
        self.assertEqual(data, {"value": [{"ref_key": "a"}]})

    def test_make_request_handles_network_error_gracefully(self):
        import requests

        with patch.object(
            self.client.session,
            "request",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            data = self.client._make_request("GET", "categories")
        self.assertEqual(data, {"value": []})


class ExChange1CCatalogEndpointsTest(TestCase):
    def setUp(self):
        self.client = ExChange1C()

    def test_get_products_uses_pagination_params(self):
        page = {"total": 1, "page": 2, "page_size": 10, "pages": 1, "items": []}
        with patch.object(self.client, "_make_request", return_value=page) as mr:
            result = self.client.get_products(page=2, page_size=10)
        self.assertEqual(result, page)
        _, kwargs = mr.call_args
        params = kwargs.get("params") or {}
        self.assertEqual(params.get("page"), 2)
        self.assertEqual(params.get("page_size"), 10)

    def test_get_all_products_iterates_all_pages(self):
        pages = [
            {
                "total": 3,
                "page": 1,
                "page_size": 2,
                "pages": 2,
                "items": [{"ref_key": "1"}, {"ref_key": "2"}],
            },
            {
                "total": 3,
                "page": 2,
                "page_size": 2,
                "pages": 2,
                "items": [{"ref_key": "3"}],
            },
        ]
        with patch.object(self.client, "get_products", side_effect=pages) as gp:
            items = self.client.get_all_products(page_size=2)
        self.assertEqual([i["ref_key"] for i in items], ["1", "2", "3"])
        self.assertEqual(gp.call_count, 2)

    def test_get_category_calls_categories_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_category()
        self.assertEqual(mr.call_args[0][1], "categories")

    def test_get_name_additional_attributes_calls_attributes_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_name_additional_attributes()
        self.assertEqual(mr.call_args[0][1], "attributes")

    def test_get_type_price_calls_pricetypes_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_type_price()
        self.assertEqual(mr.call_args[0][1], "pricetypes")

    def test_get_orders_in_shipping_calls_endpoint(self):
        with patch.object(self.client, "_make_request", return_value={"value": []}) as mr:
            self.client.get_orders_in_shipping()
        self.assertEqual(mr.call_args[0][1], "orders-in-shipping")


@override_settings(MEDIA_ROOT="/tmp/lekala_test_media")
class ExChange1CImagesTest(TestCase):
    def setUp(self):
        self.client = ExChange1C()
        self.cat = Category.objects.create(
            uuid_1C="11111111-1111-1111-1111-111111111111", name="Cat"
        )
        self.product = Product.objects.create(
            uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d",
            main_img_uuid="f5a159fc-a7fb-11ef-8a72-00155d46f78d",
            article_1C="ART1",
            code_1C="CODE1",
            data_version="v1",
            name="Товар",
            description="opis",
            stock=1,
            category=self.cat,
        )

    def test_get_img_requests_product_images_endpoint(self):
        with patch.object(
            self.client,
            "_make_request",
            return_value={"nomenclature_key": str(self.product.uuid_1C), "images": []},
        ) as mr:
            self.client.get_img(self.product.uuid_1C)
        self.assertEqual(mr.call_args[0][1], f"product-images/{self.product.uuid_1C}")

    def test_get_img_saves_images_with_main_flag(self):
        payload = {
            "nomenclature_key": str(self.product.uuid_1C),
            "images": [
                {
                    "file_uuid": "f5a159fc-a7fb-11ef-8a72-00155d46f78d",
                    "is_main": True,
                    "data_base64": ONE_PX_PNG,
                },
                {
                    "file_uuid": "00000000-0000-0000-0000-0000000000ab",
                    "is_main": False,
                    "data_base64": ONE_PX_PNG,
                },
            ],
        }
        with patch.object(self.client, "_make_request", return_value=payload):
            self.client.get_img(self.product.uuid_1C)
        imgs = self.product.images.all()
        self.assertEqual(imgs.count(), 2)
        self.assertEqual(imgs.filter(main=True).count(), 1)
        self.assertTrue(imgs.get(main=True).filename.startswith("main_"))


class GetData1CAttributesTest(TestCase):
    def setUp(self):
        self.data = GetData1C()

    def test_set_name_attribute_reads_snake_case(self):
        payload = {
            "value": [
                {
                    "ref_key": "13d974fe-ef5b-11ee-9903-00155d46f78c",
                    "description": "Материал",
                }
            ]
        }
        with patch.object(self.data, "get_name_additional_attributes", return_value=payload):
            self.data.set_name_attribute()
        obj = NameAdditionalAttributes.objects.get(
            uuid_1C="13d974fe-ef5b-11ee-9903-00155d46f78c"
        )
        self.assertEqual(obj.name_attribute, "Материал")

    def test_set_type_price_reads_snake_case(self):
        payload = {
            "value": [
                {
                    "ref_key": "e57af511-4c46-11ec-a9c8-f8cab8387a55",
                    "description": "Розничная",
                }
            ]
        }
        with patch.object(self.data, "get_type_price", return_value=payload):
            self.data.set_type_price()
        obj = TypePrices.objects.get(uuid_1C="e57af511-4c46-11ec-a9c8-f8cab8387a55")
        self.assertEqual(obj.type_price, "Розничная")
        self.assertEqual(obj.suffix, "retail_price")


class GetData1CCategoriesTest(TestCase):
    def setUp(self):
        self.data = GetData1C()

    def test_set_category_catalog_builds_tree_snake_case(self):
        root = "e19fd7c4-0000-0000-0000-000000000001"
        child = "e19fd7c4-0000-0000-0000-000000000002"
        payload = {
            "value": [
                {
                    "ref_key": root,
                    "parent_key": "00000000-0000-0000-0000-000000000000",
                    "description": "SUZUKI",
                },
                {"ref_key": child, "parent_key": root, "description": "SX4"},
            ]
        }
        with patch.object(self.data, "get_category", return_value=payload):
            self.data.set_category_catalog()
        root_obj = Category.objects.get(uuid_1C=root)
        child_obj = Category.objects.get(uuid_1C=child)
        self.assertEqual(root_obj.name, "SUZUKI")
        self.assertIsNone(root_obj.parent)
        self.assertEqual(child_obj.parent_id, root_obj.id)


class GetData1COrdersInShippingTest(TestCase):
    def setUp(self):
        self.data = GetData1C()

    def test_get_quantity_in_order_sums_from_single_endpoint(self):
        payload = {
            "value": [
                {
                    "order_key": "order-1",
                    "items": [
                        {"nomenclature_key": "A", "quantity": 2},
                        {"nomenclature_key": "B", "quantity": 1},
                    ],
                },
                {"order_key": "order-2", "items": [{"nomenclature_key": "A", "quantity": 3}]},
            ]
        }
        with patch.object(self.data, "get_orders_in_shipping", return_value=payload):
            result = self.data.get_quantity_in_order()
        self.assertEqual(result, {"A": 5, "B": 1})

    def test_get_quantity_in_order_handles_empty(self):
        with patch.object(self.data, "get_orders_in_shipping", return_value={"value": []}):
            self.assertEqual(self.data.get_quantity_in_order(), {})


class GetData1CCatalogStockTest(TestCase):
    def setUp(self):
        self.data = GetData1C()
        self.cat = Category.objects.create(
            uuid_1C="ab1b2aba-a0c8-11ee-8400-00155d46f78d", name="Категория"
        )
        NameAdditionalAttributes.objects.create(
            uuid_1C="13d974fe-ef5b-11ee-9903-00155d46f78c", name_attribute="Материал"
        )
        TypePrices.objects.create(
            uuid_1C="e57af511-4c46-11ec-a9c8-f8cab8387a55",
            type_price="Розничная",
            suffix="retail_price",
        )
        TypePrices.objects.create(
            uuid_1C="e57af510-4c46-11ec-a9c8-f8cab8387a55",
            type_price="Закупочная",
            suffix="cost_price",
        )

    def _item(self):
        return {
            "ref_key": "7e019266-24a4-11ef-8009-00155d46f78d",
            "data_version": "AAAAAAAEW/Q=",
            "parent_key": "ab1b2aba-a0c8-11ee-8400-00155d46f78d",
            "is_folder": False,
            "code": "AA-00002351",
            "article": "MEC18Z ",
            "weight_numerator": 0.3,
            "description": "Плёнка для зеркал ",
            "description_text": "Описание плёнки",
            "picture_file_key": "f5a159fc-a7fb-11ef-8a72-00155d46f78d",
            "additional_attributes": [
                {
                    "property_key": "13d974fe-ef5b-11ee-9903-00155d46f78c",
                    "description": "Материал",
                    "value": "Полиуретан",
                }
            ],
            "prices": [
                {
                    "price_type_key": "e57af510-4c46-11ec-a9c8-f8cab8387a55",
                    "price_name": "Закупочная",
                    "price": 650,
                },
                {
                    "price_type_key": "e57af511-4c46-11ec-a9c8-f8cab8387a55",
                    "price_name": "Розничная",
                    "price": 1991,
                },
            ],
            "in_stock": 46,
        }

    def test_creates_product_with_embedded_stock_and_prices(self):
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([self._item()])
        product = Product.objects.get(uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d")
        self.assertEqual(product.article_1C, "MEC18Z")
        self.assertEqual(product.code_1C, "AA-00002351")
        self.assertEqual(product.name, "Плёнка для зеркал")
        self.assertEqual(product.description, "Описание плёнки")
        self.assertEqual(product.stock, 46)
        self.assertEqual(str(product.main_img_uuid), "f5a159fc-a7fb-11ef-8a72-00155d46f78d")
        self.assertEqual(product.category_id, self.cat.id)
        prices = Prices.objects.get(product=product)
        self.assertEqual(int(prices.retail_price), 1991)
        self.assertEqual(int(prices.cost_price), 650)
        self.assertEqual(
            ValueAdditionalAttributes.objects.get(product=product).value_attribute,
            "Полиуретан",
        )

    def test_negative_stock_is_clamped_to_zero(self):
        item = self._item()
        item["in_stock"] = -5
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([item])
        self.assertEqual(
            Product.objects.get(uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d").stock,
            0,
        )

    def test_missing_price_type_defaults_to_zero(self):
        item = self._item()
        item["prices"] = [
            {
                "price_type_key": "e57af511-4c46-11ec-a9c8-f8cab8387a55",
                "price_name": "Розничная",
                "price": 1991,
            }
        ]
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([item])
        prices = Prices.objects.get(product__uuid_1C="7e019266-24a4-11ef-8009-00155d46f78d")
        self.assertEqual(int(prices.retail_price), 1991)
        self.assertEqual(int(prices.cost_price), 0)

    def test_bad_item_is_skipped_and_chunk_continues(self):
        bad = self._item()
        bad["ref_key"] = "abcdefab-1234-1234-1234-abcdefabcdef"
        bad["parent_key"] = "fefefefe-fefe-fefe-fefe-fefefefefefe"
        good = self._item()
        with patch.object(self.data, "get_img"):
            self.data.set_catalog_data_stock([bad, good])
        self.assertTrue(
            Product.objects.filter(uuid_1C=good["ref_key"]).exists()
        )
        self.assertFalse(
            Product.objects.filter(uuid_1C=bad["ref_key"]).exists()
        )

    def test_async_images_enqueues_task_not_inline(self):
        with patch.object(GetData1C, "get_img") as get_img, \
             patch("catalog.tasks.update_product_images", create=True) as upi:
            self.data.set_catalog_data_stock([self._item()], async_images=True)
        get_img.assert_not_called()
        upi.delay.assert_called_once_with("7e019266-24a4-11ef-8009-00155d46f78d")

    def test_sync_images_calls_get_img_inline(self):
        with patch.object(GetData1C, "get_img") as get_img, \
             patch("catalog.tasks.update_product_images", create=True) as upi:
            self.data.set_catalog_data_stock([self._item()], async_images=False)
        get_img.assert_called_once()
        upi.delay.assert_not_called()


class ExChange1CRetryPolicyTest(TestCase):
    def test_retry_covers_429_and_500_with_two_retries(self):
        client = ExChange1C()
        retry = client.session.get_adapter("https://x/").max_retries
        self.assertIn(429, retry.status_forcelist)
        self.assertIn(500, retry.status_forcelist)
        self.assertEqual(retry.total, 2)
        self.assertTrue(retry.respect_retry_after_header)


class CeleryRoutingSettingsTest(TestCase):
    def test_queues_and_chunk_configured(self):
        routes = dj_settings.CELERY_TASK_ROUTES
        self.assertEqual(routes["catalog.tasks.update_product_images"]["queue"], "images")
        self.assertEqual(routes["catalog.tasks.process_catalog_chunk"]["queue"], "catalog")
        self.assertEqual(routes["catalog.tasks.after_catalog_update"]["queue"], "catalog")
        self.assertEqual(routes["catalog.tasks.get_data_1C"]["queue"], "catalog")
        self.assertIsInstance(dj_settings.CATALOG_CHUNK_SIZE, int)
        self.assertEqual(dj_settings.CELERY_WORKER_PREFETCH_MULTIPLIER, 1)
        # acks_late — per-task на идемпотентных catalog/images-задачах, НЕ глобально
        # (иначе риск переотправки order_change → дубли заказов в 1С).
        self.assertFalse(getattr(dj_settings, "CELERY_TASK_ACKS_LATE", False))
        from catalog.tasks import process_catalog_chunk, update_product_images
        self.assertTrue(process_catalog_chunk.acks_late)
        self.assertTrue(update_product_images.acks_late)


class CatalogImageTaskTest(TestCase):
    @patch("catalog.tasks.ExChange1C")
    def test_update_product_images_calls_get_img(self, exc):
        from catalog.tasks import update_product_images

        update_product_images("abc-uuid")
        exc.return_value.get_img.assert_called_once_with("abc-uuid")


class CatalogChunkTaskTest(TestCase):
    @patch("catalog.tasks.GetData1C")
    def test_process_catalog_chunk_uses_async_images(self, gd):
        from catalog.tasks import process_catalog_chunk

        chunk = [{"ref_key": "x"}]
        process_catalog_chunk(chunk)
        gd.return_value.set_catalog_data_stock.assert_called_once_with(
            chunk, async_images=True
        )


class CatalogAfterUpdateTest(TestCase):
    def test_after_catalog_update_triggers_marketplaces(self):
        import catalog.tasks as t

        with patch.object(t, "update_remains_ozon") as ozon, \
             patch.object(t, "update_remains_wb") as wb, \
             patch.object(t, "update_stock_ali") as ali:
            t.after_catalog_update()
        ozon.delay.assert_called_once_with()
        wb.delay.assert_called_once_with()
        ali.delay.assert_called_once_with()

    def test_after_catalog_update_accepts_positional_results(self):
        import catalog.tasks as t

        with patch.object(t, "update_remains_ozon") as ozon, \
             patch.object(t, "update_remains_wb") as wb, \
             patch.object(t, "update_stock_ali") as ali:
            t.after_catalog_update([1, 2, 3])
        ozon.delay.assert_called_once_with()
        wb.delay.assert_called_once_with()
        ali.delay.assert_called_once_with()


class GetData1COrchestratorTest(TestCase):
    @override_settings(CATALOG_CHUNK_SIZE=2)
    @patch("catalog.tasks.after_catalog_update")
    @patch("catalog.tasks.chord", create=True)
    @patch("catalog.tasks.group", create=True)
    @patch("catalog.tasks.process_catalog_chunk")
    @patch("catalog.tasks.GetData1C")
    def test_dispatches_chord_of_chunks(self, gd, pcc, group_mock, chord_mock, after):
        inst = gd.return_value
        inst.get_all_products.return_value = [
            {"ref_key": "1"}, {"ref_key": "2"}, {"ref_key": "3"}
        ]
        from catalog.tasks import get_data_1C

        get_data_1C()
        inst.set_name_attribute.assert_called_once()
        inst.set_type_price.assert_called_once()
        inst.set_category_catalog.assert_called_once()
        self.assertEqual(pcc.s.call_count, 2)
        chord_mock.assert_called_once_with(group_mock.return_value)
        chord_mock.return_value.assert_called_once_with(after.s.return_value)

    @override_settings(CATALOG_CHUNK_SIZE=2)
    @patch("catalog.tasks.chord", create=True)
    @patch("catalog.tasks.GetData1C")
    def test_empty_catalog_does_not_dispatch(self, gd, chord_mock):
        gd.return_value.get_all_products.return_value = []
        from catalog.tasks import get_data_1C

        get_data_1C()
        chord_mock.assert_not_called()
