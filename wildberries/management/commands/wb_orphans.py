import difflib

from django.core.management.base import BaseCommand

from catalog.models import Product
from src.lekala_class.class_marketplace.WB import WBItemCard
from wildberries.models import WBData
from wildberries.tasks import iter_wb_cards

# Насколько название карточки должно совпасть с названием товара, чтобы
# считать кандидата правдоподобным.
NAME_RATIO = 0.75


class Command(BaseCommand):
    help = (
        "Карточки WB, которым не соответствует ни один товар по артикулу. "
        "Для каждой подбирает кандидата в базе по баркоду и названию, чтобы "
        "было видно, где артикул просто разъехался, а где товара нет вовсе. "
        "Ничего не меняет."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--param",
            choices=("all", "withoutImg", "withImg"),
            default="all",
            help="Какие карточки обходить",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=0,
            help="Сколько строк показать в каждой группе (0 — все)",
        )

    def handle(self, *args, **options):
        api = WBItemCard()

        articles = dict(Product.objects.values_list("article_1C", "id"))
        names = {
            product_id: name
            for product_id, name in Product.objects.values_list("id", "name")
        }
        by_barcode = {
            str(barcode): product_id
            for barcode, product_id in WBData.objects.exclude(
                wb_barcode__isnull=True
            ).values_list("wb_barcode", "product_id")
        }
        name_index = {name.lower(): pid for pid, name in names.items()}

        matched = 0
        by_barcode_hits = []
        by_name_hits = []
        no_match = []

        for page in iter_wb_cards(api, options["param"]):
            for card in page["cards"]:
                code = card.get("vendorCode")
                if code in articles:
                    matched += 1
                    continue

                title = (card.get("title") or "").strip()
                sizes = card.get("sizes") or []
                skus = (sizes[0].get("skus") if sizes else None) or []
                barcode = str(skus[0]) if skus else None

                product_id = by_barcode.get(barcode) if barcode else None
                if product_id:
                    by_barcode_hits.append((code, title, names.get(product_id), "баркод"))
                    continue

                product_id = name_index.get(title.lower())
                if product_id is None and title:
                    close = difflib.get_close_matches(
                        title.lower(), name_index.keys(), n=1, cutoff=NAME_RATIO
                    )
                    if close:
                        product_id = name_index[close[0]]

                if product_id:
                    by_name_hits.append((code, title, names.get(product_id), "название"))
                else:
                    no_match.append((code, title))

        total_orphans = len(by_barcode_hits) + len(by_name_hits) + len(no_match)
        self.stdout.write(f"Карточек привязано по артикулу: {matched}")
        self.stdout.write(f"Карточек без товара по артикулу: {total_orphans}\n")

        show = options["show"]

        self._dump(
            f"=== Кандидат найден по баркоду: {len(by_barcode_hits)} ===\n"
            "    Тот же товар, артикул разъехался. Карточку НЕ удалять — "
            "поправить артикул через update_vendor_code_wb.",
            by_barcode_hits, show, with_candidate=True,
        )
        self._dump(
            f"=== Кандидат найден по названию: {len(by_name_hits)} ===\n"
            "    Похоже на тот же товар. Проверить глазами перед решением.",
            by_name_hits, show, with_candidate=True,
        )
        self._dump(
            f"=== Товара в базе нет: {len(no_match)} ===\n"
            "    Кандидатов не нашлось — это и есть кандидаты в корзину WB.",
            no_match, show, with_candidate=False,
        )

    def _dump(self, title, rows, show, with_candidate):
        if not rows:
            return
        self.stdout.write(f"\n{title}")
        visible = rows if show == 0 else rows[:show]
        for row in visible:
            if with_candidate:
                code, card_title, product_name, source = row
                self.stdout.write(f"    {str(code)[:24]:<24} карточка: {card_title[:45]}")
                self.stdout.write(f"    {'':<24} товар   : {str(product_name)[:45]} ({source})")
            else:
                code, card_title = row
                self.stdout.write(f"    {str(code)[:24]:<24} {card_title[:50]}")
        if show and len(rows) > show:
            self.stdout.write(f"    ... ещё {len(rows) - show}, весь список — с --show 0")
