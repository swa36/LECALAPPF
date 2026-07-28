from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Product
from order.models import (
    ItemInOrderAli,
    ItemInOrderAvito,
    ItemInOrderOzon,
    OrderAvito,
    OrderWB,
)
from src.lekala_class.class_1C.GetData1C import GetData1C

# Доля товаров, выше которой команда не удаляет ничего без --force:
# похоже на сбой выгрузки, а не на реальную чистку в 1С.
SANITY_LIMIT = 0.2


class Command(BaseCommand):
    help = (
        "Удаляет товары, которых больше нет в выгрузке 1С. Товары, "
        "встречающиеся в заказах, не трогает: у OrderAvito каскад снёс бы "
        "сам заказ, а позиции заказов ссылаются на товар через "
        "GenericForeignKey, который Django не защищает. "
        "По умолчанию только отчёт, удаление — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить удаление (без флага — только отчёт)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Игнорировать защиту от массового удаления",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=30,
            help="Сколько товаров показать в отчёте (0 — все)",
        )
        parser.add_argument(
            "--zero-stock",
            action="store_true",
            help=(
                "Вместо удаления обнулить остаток у всех товаров, которых нет "
                "в 1С: они уходят из продажи, но связки и история остаются"
            ),
        )

    def handle(self, *args, **options):
        self.stdout.write("Качаю каталог из 1С...")
        items = GetData1C().get_all_products()
        if not items:
            self.stderr.write(
                self.style.ERROR(
                    "1С не вернула ни одного товара — прерываю, "
                    "иначе удалился бы весь каталог сайта."
                )
            )
            return

        api_uuids = {i["ref_key"] for i in items}
        total = Product.objects.count()
        self.stdout.write(f"Товаров в 1С: {len(api_uuids)}, в БД сайта: {total}\n")

        ghosts = [p for p in Product.objects.all() if str(p.uuid_1C) not in api_uuids]
        if not ghosts:
            self.stdout.write(self.style.SUCCESS("Лишних товаров нет"))
            return

        in_orders = self._products_in_orders()

        removable = [p for p in ghosts if p.pk not in in_orders]
        keep = [p for p in ghosts if p.pk in in_orders]

        self.stdout.write(f"Товаров без соответствия в 1С: {len(ghosts)}")
        self.stdout.write(f"  из них в заказах (не трогаем): {len(keep)}")
        self.stdout.write(f"  к удалению: {len(removable)}\n")

        with_stock = [p for p in removable if p.stock > 0]
        with_wb = [p for p in removable if hasattr(p, "wb")]
        self.stdout.write("Среди тех, что под удаление:")
        self.stdout.write(f"  с остатком > 0: {len(with_stock)}")
        self.stdout.write(f"  с карточкой WB: {len(with_wb)}")
        if with_wb:
            self.stdout.write(
                "  Карточки на WB сами не исчезнут: после удаления товара "
                "остатки и цены по ним перестанут обновляться.\n"
            )

        show = options["show"]
        self._dump("=== К удалению ===", removable, show)
        self._dump("=== Оставляем: товар есть в заказах ===", keep, show)

        if options["zero_stock"]:
            if not options["apply"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"\nЭто только отчёт. Обнулить остаток у {len(ghosts)} товаров — "
                        "запусти с --zero-stock --apply"
                    )
                )
                return
            updated = Product.objects.filter(
                pk__in=[p.pk for p in ghosts], stock__gt=0
            ).update(stock=0)
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nОстаток обнулён у {updated} товаров. Ничего не удалено: "
                    "связки, цены и история заказов на месте."
                )
            )
            return

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nЭто только отчёт.\n"
                    "  --zero-stock --apply — снять с продажи, обратимо\n"
                    "  --apply              — удалить безвозвратно"
                )
            )
            return

        if not options["force"] and total and len(removable) / total > SANITY_LIMIT:
            self.stderr.write(
                self.style.ERROR(
                    f"\nПод удаление попало {len(removable)} из {total} товаров "
                    f"(> {SANITY_LIMIT:.0%}). Похоже на неполную выгрузку из 1С. "
                    "Если это действительно так задумано — добавь --force."
                )
            )
            return

        with transaction.atomic():
            deleted, details = Product.objects.filter(
                pk__in=[p.pk for p in removable]
            ).delete()

        self.stdout.write(self.style.SUCCESS(f"\nУдалено объектов всего: {deleted}"))
        for model, number in sorted(details.items()):
            self.stdout.write(f"  {model}: {number}")
        self.stdout.write(
            f"Осталось товаров: {Product.objects.count()}. "
            "Файлы изображений на диске остаются — их чистить отдельно."
        )

    def _products_in_orders(self):
        """pk товаров, на которые ссылается хоть один заказ."""
        content_type = ContentType.objects.get_for_model(Product)
        referenced = set()

        for model in (ItemInOrderAvito, ItemInOrderOzon, ItemInOrderAli, OrderWB):
            values = model.objects.filter(content_type=content_type).values_list(
                "object_id", flat=True
            )
            for object_id in values:
                if object_id and str(object_id).isdigit():
                    referenced.add(int(object_id))

        referenced.update(
            OrderAvito.objects.filter(product__isnull=False).values_list(
                "product_id", flat=True
            )
        )
        return referenced

    def _dump(self, title, products, show):
        if not products:
            return
        self.stdout.write(title)
        rows = products if show == 0 else products[:show]
        for product in rows:
            marketplaces = []
            if hasattr(product, "wb"):
                marketplaces.append(f"WB:{product.wb.wb_id}")
            if hasattr(product, "ozon"):
                marketplaces.append("OZON")
            if hasattr(product, "ali"):
                marketplaces.append("ALI")
            self.stdout.write(
                f"    {product.uuid_1C}  stock={product.stock:<5} "
                f"{product.article_1C[:24]:<24} "
                f"{'/'.join(marketplaces) or '—':<18} {product.name[:40]}"
            )
        if show and len(products) > show:
            self.stdout.write(f"    ... ещё {len(products) - show}, весь список — с --show 0")
        self.stdout.write("")
