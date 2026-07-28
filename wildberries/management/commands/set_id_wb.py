from django.core.management.base import BaseCommand

from catalog.models import Product
from wildberries.tasks import set_id_wb

PARAMS = ('all', 'withoutImg', 'withImg')


class Command(BaseCommand):
    help = (
        "Привязывает карточки WB к товарам: заполняет WBData по совпадению "
        "article_1C и vendorCode. Какие карточки обходить — задаётся --param."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--param",
            choices=PARAMS,
            default="all",
            help="Какие карточки обходить: all (по умолчанию), withoutImg, withImg",
        )

    def handle(self, *args, **options):
        param = options["param"]
        before = Product.objects.filter(wb__isnull=False).count()
        self.stdout.write(f"Обход карточек WB: {param}")
        self.stdout.write(f"Товаров со связкой WB до запуска: {before}\n")

        set_id_wb(param=param)

        after = Product.objects.filter(wb__isnull=False).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"\nТоваров со связкой WB стало: {after} (прибавилось {after - before})"
            )
        )
        self.stdout.write(
            "Строки без описания выше — карточки, которые привязать не вышло, "
            "причина указана рядом с артикулом."
        )
