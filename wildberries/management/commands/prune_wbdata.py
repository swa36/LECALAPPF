from django.core.management.base import BaseCommand

from src.lekala_class.class_marketplace.WB import WBItemCard
from wildberries.models import WBData


class Command(BaseCommand):
    help = (
        "Удаляет записи WBData, чьих карточек больше нет на WB. Карточки в "
        "корзине по умолчанию сохраняются: их ещё можно восстановить. "
        "По умолчанию только отчёт, удаление — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить удаление (без флага — только отчёт)",
        )
        parser.add_argument(
            "--include-trash",
            action="store_true",
            help="Удалять и те записи, чьи карточки лежат в корзине WB",
        )

    def handle(self, *args, **options):
        api = WBItemCard()

        live = self._collect_live(api)
        if live is None:
            return
        trashed = self._collect_trashed(api)

        self.stdout.write(
            f"Карточек на WB: {len(live)}, в корзине: {len(trashed)}, "
            f"записей WBData: {WBData.objects.count()}\n"
        )

        missing = []
        in_trash = []
        for row in WBData.objects.select_related("product").all():
            if row.wb_id in live:
                continue
            if row.wb_id in trashed:
                in_trash.append(row)
            else:
                missing.append(row)

        if in_trash:
            self.stdout.write("=== Карточки в корзине WB ===")
            for row in in_trash:
                self.stdout.write(
                    f"  nmID {row.wb_id}  offer_id={row.offer_id}  {row.product.name[:50]}"
                )
            self.stdout.write(
                "  Их ещё можно восстановить (v2/cards/recover). "
                "Через 30 дней без остатков WB удалит их сам.\n"
            )

        if missing:
            self.stdout.write("=== Карточек нет на WB вообще ===")
            for row in missing:
                self.stdout.write(
                    f"  nmID {row.wb_id}  offer_id={row.offer_id}  {row.product.name[:50]}"
                )
        else:
            self.stdout.write("Записей без карточки на WB нет")

        to_delete = missing + (in_trash if options["include_trash"] else [])
        if not to_delete:
            return

        self.stdout.write(f"\nК удалению записей WBData: {len(to_delete)}")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("\nЭто только отчёт. Для удаления запусти с --apply")
            )
            return

        deleted, _ = WBData.objects.filter(
            pk__in=[row.pk for row in to_delete]
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Удалено записей: {deleted}. Товары остались, снята только связь с WB."
            )
        )

    def _collect_live(self, api):
        """nmID всех актуальных карточек. None — если выгрузка сорвалась."""
        found = set()
        cursor = None
        while True:
            data = api.get_items(param="all", cursor=cursor)
            cards = data.get("cards")
            if cards is None:
                self.stderr.write(
                    self.style.ERROR(
                        "WB не вернул список карточек — прерываю, "
                        "иначе удалились бы живые связки."
                    )
                )
                return None
            found.update(card["nmID"] for card in cards)

            cursor_data = data.get("cursor") or {}
            if len(cards) < 100 or "nmID" not in cursor_data or "updatedAt" not in cursor_data:
                return found
            cursor = {
                "updatedAt": cursor_data["updatedAt"],
                "nmID": cursor_data["nmID"],
                "limit": 100,
            }

    def _collect_trashed(self, api):
        """nmID карточек в корзине."""
        found = set()
        cursor = None
        while True:
            data = api.get_trash(cursor=cursor)
            cards = data.get("cards") or []
            found.update(card["nmID"] for card in cards)

            cursor_data = data.get("cursor") or {}
            if len(cards) < 100 or "nmID" not in cursor_data or "trashedAt" not in cursor_data:
                return found
            cursor = {
                "trashedAt": cursor_data["trashedAt"],
                "nmID": cursor_data["nmID"],
                "limit": 100,
            }
