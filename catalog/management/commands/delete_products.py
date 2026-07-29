from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Product
from order.models import (
    ItemInOrderAli,
    ItemInOrderAvito,
    ItemInOrderOzon,
    ItemInOrderYM,
    OrderAvito,
    OrderWB,
)

FIELDS = {
    "article": "article_1C",
    "code": "code_1C",
}

# Позиции заказов ссылаются на товар через GenericForeignKey: Django его не
# каскадит, поэтому после удаления товара остались бы битые строки. Заказ с
# такой позицией удаляем целиком — половина заказа хуже, чем его отсутствие.
ITEM_MODELS = (
    (ItemInOrderAvito, "Avito"),
    (ItemInOrderOzon, "Ozon"),
    (ItemInOrderAli, "Ali"),
    (ItemInOrderYM, "YaMarket"),
)


class Command(BaseCommand):
    help = (
        "Удаляет товары по артикулу (или коду) 1С вместе со всеми заказами, "
        "которые на них ссылаются, чтобы синхронизация завела их заново. "
        "Каскадом уходят связки WB/Ozon/Ali, цены, картинки и доп. реквизиты. "
        "По умолчанию только отчёт, удаление — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "values",
            nargs="*",
            help="Артикулы (или коды) 1С. С пробелами — в кавычках",
        )
        parser.add_argument(
            "--by",
            choices=sorted(FIELDS),
            default="article",
            help="По какому полю искать товары (по умолчанию article)",
        )
        parser.add_argument(
            "--file",
            help=(
                "Файл со списком, по одному значению в строке. Хвост «,N» "
                "отбрасывается — можно скормить вывод check_duplicates"
            ),
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить удаление (без флага — только отчёт)",
        )

    def handle(self, *args, **options):
        field = FIELDS[options["by"]]
        values = self._collect_values(options)
        if not values:
            self.stderr.write(self.style.ERROR("Не передано ни одного значения"))
            return

        products = list(Product.objects.filter(**{f"{field}__in": values}))
        found = {getattr(p, field) for p in products}
        for value in values:
            if value not in found:
                self.stdout.write(
                    self.style.WARNING(f"Не найден товар: {value} (поле {field})")
                )

        if not products:
            self.stdout.write("Удалять нечего")
            return

        pks = [str(p.pk) for p in products]
        orders = self._orders_for(pks, products)

        self._report(products, orders)

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nЭто только отчёт. Удалить безвозвратно — добавь --apply"
                )
            )
            return

        with transaction.atomic():
            deleted_orders = 0
            for queryset in orders.values():
                deleted_orders += queryset.delete()[0]
            deleted, details = Product.objects.filter(
                pk__in=[p.pk for p in products]
            ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"\nУдалено объектов заказов: {deleted_orders}, "
                f"объектов каталога: {deleted}"
            )
        )
        for model, number in sorted(details.items()):
            self.stdout.write(f"  {model}: {number}")
        self.stdout.write(
            f"Осталось товаров: {Product.objects.count()}. Файлы изображений на "
            "диске остаются. Товары вернутся при следующей синхронизации с 1С, "
            "если они есть в выгрузке."
        )

    def _collect_values(self, options):
        values = list(options["values"])
        if options["file"]:
            with open(options["file"], encoding="utf-8") as source:
                for line in source:
                    value = self._strip_count(line.strip())
                    if value:
                        values.append(value)
        return values

    @staticmethod
    def _strip_count(line):
        """«Haval Jolion 2020 -,2» → «Haval Jolion 2020 -»."""
        head, sep, tail = line.rpartition(",")
        if sep and tail.strip().isdigit():
            return head.strip()
        return line

    def _orders_for(self, pks, products):
        """Заказы, которые ссылаются на удаляемые товары, по типам."""
        content_type = ContentType.objects.get_for_model(Product)
        orders = {
            "Avito (товар в заказе)": OrderAvito.objects.filter(product__in=products),
            "WB": OrderWB.objects.filter(content_type=content_type, object_id__in=pks),
        }
        for model, label in ITEM_MODELS:
            order_ids = model.objects.filter(
                content_type=content_type, object_id__in=pks
            ).values_list("order_num_id", flat=True)
            parent = model._meta.get_field("order_num").related_model
            orders[f"{label} (позиция заказа)"] = parent.objects.filter(
                pk__in=list(order_ids)
            )
        return orders

    def _report(self, products, orders):
        self.stdout.write(f"К удалению товаров: {len(products)}")
        for product in products:
            marketplaces = []
            if hasattr(product, "wb"):
                marketplaces.append(f"WB:{product.wb.wb_id}")
            if hasattr(product, "ozon"):
                marketplaces.append("OZON")
            if hasattr(product, "ali"):
                marketplaces.append("ALI")
            self.stdout.write(
                f"    {product.uuid_1C}  {product.code_1C:<14} "
                f"stock={product.stock:<5} archive={str(product.is_archive):<5} "
                f"{'/'.join(marketplaces) or '—':<16} "
                f"{product.article_1C[:28]:<28} {product.name[:40]}"
            )

        total_orders = 0
        for label, queryset in orders.items():
            count = queryset.count()
            if not count:
                continue
            total_orders += count
            numbers = list(queryset.values_list("number_1C", flat=True)[:10])
            tail = ", ..." if count > 10 else ""
            self.stdout.write(
                f"\nЗаказы {label}: {count} — {', '.join(str(n) for n in numbers)}{tail}"
            )
        if not total_orders:
            self.stdout.write("\nЗаказов, ссылающихся на эти товары, нет")
