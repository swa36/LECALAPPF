import time

from django.core.management.base import BaseCommand

from catalog.models import Product
from src.lekala_class.class_marketplace.WB import WBItemCard

# Лимит метода — 3 запроса в минуту, поэтому между пачками ждём 20 секунд.
BATCH_SIZE = 500
PAUSE_SECONDS = 20


class Command(BaseCommand):
    help = (
        "Переносит в корзину WB карточки товаров с меткой «архив». Карточки, "
        "уже лежащие в корзине, пропускает. Восстановление — вручную через "
        "v2/cards/recover. По умолчанию только отчёт, перенос — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить перенос (без флага — только отчёт)",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=30,
            help="Сколько карточек показать в отчёте (0 — все)",
        )

    def handle(self, *args, **options):
        products = list(
            Product.objects.filter(is_archive=True, wb__isnull=False)
            .select_related("wb")
            .exclude(wb__wb_id__isnull=True)
        )
        if not products:
            self.stdout.write(self.style.SUCCESS("Архивных товаров с карточкой WB нет"))
            return

        self.stdout.write(f"Архивных товаров с карточкой WB: {len(products)}")

        api = WBItemCard()
        trashed = self._collect_trashed(api)
        if trashed is None:
            return
        self.stdout.write(f"Уже в корзине WB: {len(trashed)}\n")

        pending = [p for p in products if p.wb.wb_id not in trashed]
        already = len(products) - len(pending)
        if already:
            self.stdout.write(f"Пропускаю, они уже в корзине: {already}")
        if not pending:
            self.stdout.write(self.style.SUCCESS("Переносить нечего"))
            return

        self.stdout.write(f"К переносу в корзину: {len(pending)}\n")
        show = options["show"]
        rows = pending if show == 0 else pending[:show]
        for product in rows:
            self.stdout.write(
                f"    nmID {product.wb.wb_id:<12} {product.article_1C[:24]:<24} "
                f"stock={product.stock:<4} {product.name[:40]}"
            )
        if show and len(pending) > show:
            self.stdout.write(f"    ... ещё {len(pending) - show}, весь список — с --show 0")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("\nЭто только отчёт. Для переноса запусти с --apply")
            )
            return

        moved = 0
        nm_ids = [p.wb.wb_id for p in pending]
        for start in range(0, len(nm_ids), BATCH_SIZE):
            chunk = nm_ids[start:start + BATCH_SIZE]
            response = api.del_item(data=chunk)
            if isinstance(response, dict) and response.get("error"):
                self.stderr.write(
                    self.style.ERROR(f"WB вернул ошибку: {response.get('errorText')}")
                )
                continue
            moved += len(chunk)
            self.stdout.write(f"Перенесено: {moved} из {len(nm_ids)}")
            if start + BATCH_SIZE < len(nm_ids):
                time.sleep(PAUSE_SECONDS)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nВ корзину отправлено карточек: {moved}. "
                "Карточка продаётся, пока по ней есть остатки, — убедись, что "
                "update_remains_wb уже разнёс нули. WB чистит корзину через 30 дней."
            )
        )

    def _collect_trashed(self, api):
        """nmID карточек в корзине. None — если выгрузка сорвалась."""
        found = set()
        cursor = None
        while True:
            data = api.get_trash(cursor=cursor)
            cards = data.get("cards")
            if cards is None:
                self.stderr.write(
                    self.style.ERROR(
                        "WB не вернул содержимое корзины — прерываю, иначе "
                        "карточки уехали бы в корзину повторно."
                    )
                )
                return None
            found.update(card["nmID"] for card in cards)

            cursor_data = data.get("cursor") or {}
            if len(cards) < 100 or "nmID" not in cursor_data or "trashedAt" not in cursor_data:
                return found
            cursor = {
                "trashedAt": cursor_data["trashedAt"],
                "nmID": cursor_data["nmID"],
                "limit": 100,
            }
