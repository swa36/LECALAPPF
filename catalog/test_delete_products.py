import tempfile
import uuid
from io import StringIO

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from catalog.models import Product
from order.models import (
    ItemInOrderAvito,
    ItemInOrderOzon,
    OrderAvito,
    OrderOzon,
    OrderWB,
)


def make_product(article, code):
    return Product.objects.create(
        uuid_1C=uuid.uuid4(),
        article_1C=article,
        code_1C=code,
        data_version="AAA=",
        name=f"Товар {article}",
        description="",
        stock=10,
    )


class DeleteProductsCommandTest(TestCase):
    def setUp(self):
        self.doomed = make_product("ML20010Z", "AA-00000001")
        self.twin = make_product("ML20010Z", "AA-00000002")
        self.spared = make_product("KEEPME", "AA-00000003")

    def _call(self, *args):
        out = StringIO()
        call_command("delete_products", "ML20010Z", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_without_apply_nothing_is_deleted(self):
        output = self._call()
        self.assertEqual(Product.objects.count(), 3)
        self.assertIn("--apply", output)

    def test_apply_deletes_every_product_with_the_article(self):
        self._call("--apply")
        self.assertFalse(Product.objects.filter(article_1C="ML20010Z").exists())
        self.assertTrue(Product.objects.filter(pk=self.spared.pk).exists())

    def test_avito_order_linked_by_foreign_key_is_deleted(self):
        order = OrderAvito.objects.create(number_1C="A-1", product=self.doomed)
        other = OrderAvito.objects.create(number_1C="A-2", product=self.spared)
        self._call("--apply")
        self.assertFalse(OrderAvito.objects.filter(pk=order.pk).exists())
        self.assertTrue(OrderAvito.objects.filter(pk=other.pk).exists())

    def test_order_is_deleted_whole_when_an_item_points_at_the_product(self):
        ct = ContentType.objects.get_for_model(Product)
        order = OrderOzon.objects.create(number_1C="O-1")
        ItemInOrderOzon.objects.create(
            order_num=order, content_type=ct, object_id=str(self.doomed.pk), price=10
        )
        # вторая позиция того же заказа — на уцелевший товар, но заказ уходит целиком,
        # иначе в базе остался бы заказ с недостающими строками
        ItemInOrderOzon.objects.create(
            order_num=order, content_type=ct, object_id=str(self.spared.pk), price=20
        )
        self._call("--apply")
        self.assertFalse(OrderOzon.objects.filter(pk=order.pk).exists())
        self.assertEqual(ItemInOrderOzon.objects.count(), 0)

    def test_wb_order_pointing_at_the_product_is_deleted(self):
        ct = ContentType.objects.get_for_model(Product)
        order = OrderWB.objects.create(
            number_1C="W-1", content_type=ct, object_id=str(self.twin.pk)
        )
        other = OrderWB.objects.create(
            number_1C="W-2", content_type=ct, object_id=str(self.spared.pk)
        )
        self._call("--apply")
        self.assertFalse(OrderWB.objects.filter(pk=order.pk).exists())
        self.assertTrue(OrderWB.objects.filter(pk=other.pk).exists())

    def test_orders_of_untouched_products_survive(self):
        ct = ContentType.objects.get_for_model(Product)
        order = OrderAvito.objects.create(number_1C="A-3")
        ItemInOrderAvito.objects.create(
            order_num=order, content_type=ct, object_id=str(self.spared.pk), price=10
        )
        self._call("--apply")
        self.assertTrue(OrderAvito.objects.filter(pk=order.pk).exists())
        self.assertEqual(ItemInOrderAvito.objects.count(), 1)

    def test_unknown_article_is_reported_and_nothing_is_deleted(self):
        out = StringIO()
        call_command("delete_products", "НЕТ-ТАКОГО", "--apply", stdout=out, stderr=out)
        self.assertEqual(Product.objects.count(), 3)
        self.assertIn("НЕТ-ТАКОГО", out.getvalue())

    def test_values_are_read_from_file(self):
        path = tempfile.mktemp(suffix=".txt")
        with open(path, "w", encoding="utf-8") as target:
            target.write("ML20010Z\n\nKEEPME\n")
        out = StringIO()
        call_command("delete_products", "--file", path, "--apply", stdout=out, stderr=out)
        self.assertEqual(Product.objects.count(), 0)

    def test_duplicate_report_lines_drop_their_count_suffix(self):
        # check_duplicates печатает «Haval Jolion 2020 -,2» — счётчик не часть артикула
        path = tempfile.mktemp(suffix=".txt")
        with open(path, "w", encoding="utf-8") as target:
            target.write("ML20010Z,2\n")
        out = StringIO()
        call_command("delete_products", "--file", path, "--apply", stdout=out, stderr=out)
        self.assertFalse(Product.objects.filter(article_1C="ML20010Z").exists())
        self.assertTrue(Product.objects.filter(pk=self.spared.pk).exists())

    def test_products_can_be_selected_by_code_1c(self):
        out = StringIO()
        call_command(
            "delete_products", "AA-00000001", "--by", "code", "--apply", stdout=out, stderr=out
        )
        self.assertFalse(Product.objects.filter(pk=self.doomed.pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.twin.pk).exists())
