from django.core.management.base import BaseCommand
from django.db.models import Count

from catalog.models import Product

FIELDS = {
    "article": "article_1C",
    "code": "code_1C",
    "name": "name",
}


class Command(BaseCommand):
    help = (
        "Ищет товары-дубли по артикулу 1С. Дубль ломает связки с "
        "маркетплейсами: там товар ищется через Product.objects.get(article_1C=...), "
        "что на дублях падает с MultipleObjectsReturned. Ничего не меняет."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--by",
            choices=sorted(FIELDS),
            default="article",
            help="По какому полю искать дубли (по умолчанию article)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Показать не больше N групп (0 — все)",
        )
        parser.add_argument(
            "--check-1c",
            action="store_true",
            help="Сверить каждый товар с выгрузкой 1С (качает весь каталог)",
        )

    def handle(self, *args, **options):
        field = FIELDS[options["by"]]

        api_uuids = None
        if options["check_1c"]:
            from src.lekala_class.class_1C.GetData1C import GetData1C

            self.stdout.write("Качаю каталог из 1С для сверки...")
            items = GetData1C().get_all_products()
            if not items:
                self.stderr.write(self.style.ERROR("1С не вернула товары — сверка невозможна"))
                return
            api_uuids = {i["ref_key"] for i in items}
            self.stdout.write(f"Товаров в выгрузке 1С: {len(api_uuids)}\n")

        groups = (
            Product.objects.exclude(**{field: ""})
            .exclude(**{f"{field}__isnull": True})
            .values(field)
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .order_by("-total", field)
        )

        count = groups.count()
        if not count:
            self.stdout.write(self.style.SUCCESS(f"Дублей по «{field}» нет"))
            return

        self.stdout.write(
            f"Групп-дублей по «{field}»: {count} "
            f"(всего товаров в базе: {Product.objects.count()})\n"
        )

        limit = options["limit"]
        shown = groups[:limit] if limit else groups

        blocking = 0
        ghosts = 0
        for group in shown:
            value = group[field]
            self.stdout.write(f"{value}  ×{group['total']}")

            products = Product.objects.filter(**{field: value}).select_related("category")
            linked = 0
            for product in products:
                marketplaces = []
                if hasattr(product, "wb"):
                    marketplaces.append(f"WB:{product.wb.wb_id}")
                    linked += 1
                if hasattr(product, "ozon"):
                    marketplaces.append("OZON")
                if hasattr(product, "ali"):
                    marketplaces.append("ALI")

                if api_uuids is None:
                    in_1c = ""
                elif str(product.uuid_1C) in api_uuids:
                    in_1c = "есть в 1С    "
                else:
                    in_1c = "НЕТ В 1С     "
                    ghosts += 1

                self.stdout.write(
                    f"    {product.uuid_1C}  stock={product.stock:<5} {in_1c}"
                    f"кат: {str(product.category)[:20]:<20} "
                    f"{'/'.join(marketplaces) or '—':<18} {product.name[:45]}"
                )

            if linked:
                blocking += 1
                self.stdout.write(
                    self.style.WARNING(
                        "    ↑ есть привязка к WB: задачи артикулов, цен и "
                        "остатков на этой группе падают"
                    )
                )

        if limit and count > limit:
            self.stdout.write(f"\n... показано {limit} из {count}, весь список — без --limit")

        self.stdout.write(f"\nГрупп с привязкой к WB: {blocking}.")
        if ghosts:
            self.stdout.write(
                self.style.WARNING(
                    f"Товаров, которых нет в выгрузке 1С: {ghosts}. "
                    "Это остатки от удалённой или пересозданной номенклатуры — "
                    "синхронизация их не трогает и не удаляет."
                )
            )
        self.stdout.write(
            "Дубли артикулов у живых товаров правятся в 1С — "
            "на стороне сайта их чинить нечем."
        )
