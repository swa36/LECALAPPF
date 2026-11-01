import time

from django.core.management.base import BaseCommand

from catalog.models import Product
from src.lekala_class.class_marketplace.WB import WBItemCard
from src.lekala_class.class_marketplace.WBItem import (
    TNVED_CODE,
    card_with_tnved,
    glass_category_ids,
    has_tnved,
)

# v2/cards/update: до 3000 карточек в запросе, лимит 10 запросов в минуту.
BATCH_SIZE = 100
PAUSE_SECONDS = 7


class Command(BaseCommand):
    help = (
        f"Проставляет ТН ВЭД {TNVED_CODE} карточкам плёнок на WB, где его нет. "
        "Стёкла пропускает. "
        "Карточка берётся с WB как есть, меняется только ТН ВЭД. "
        "По умолчанию только отчёт, отправка — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Отправить на WB (без флага — только отчёт)")
        parser.add_argument("--limit", type=int, default=None,
                            help="Обработать только первые N карточек")
        parser.add_argument("--show", type=int, default=10,
                            help="Сколько карточек показать в отчёте (0 — все)")

    def handle(self, *args, **options):
        api = WBItemCard()
        cards = self._collect_cards(api)
        if cards is None:
            return

        articles = set(Product.objects.values_list("article_1C", flat=True))
        glass = set(
            Product.objects.filter(category_id__in=glass_category_ids())
            .values_list("article_1C", flat=True)
        )
        done = [card for card in cards if has_tnved(card)]
        rest = [card for card in cards if not has_tnved(card)]
        glass_cards = [card for card in rest if card.get("vendorCode") in glass]
        unknown = [card for card in rest if card.get("vendorCode") not in articles]
        pending = [
            card for card in rest
            if card.get("vendorCode") in articles and card.get("vendorCode") not in glass
        ]
        self.stdout.write(
            f"Карточек на WB: {len(cards)}\n"
            f"    уже с ТН ВЭД {TNVED_CODE}: {len(done)}\n"
            f"    стёкла, пропускаю (им нужен 7007… в предмете 9226): {len(glass_cards)}\n"
            f"    артикула нет в базе, пропускаю: {len(unknown)}\n"
            f"    к обновлению: {len(pending)}"
        )
        for card in unknown[:20]:
            self.stdout.write(f"    нет в базе: nmID {card['nmID']} {card.get('vendorCode')} {card.get('title', '')[:50]}")
        if options["limit"] is not None:
            pending = pending[:options["limit"]]
            self.stdout.write(f"Ограничение --limit: берём первые {len(pending)}")
        if not pending:
            self.stdout.write(self.style.SUCCESS("Обновлять нечего"))
            return

        show = options["show"]
        for card in pending if show == 0 else pending[:show]:
            self.stdout.write(
                f"    nmID {card['nmID']:<12} {card.get('vendorCode', '')[:24]:<24} "
                f"{card.get('title', '')[:50]}"
            )
        if show and len(pending) > show:
            self.stdout.write(f"    ... ещё {len(pending) - show}, весь список — с --show 0")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("\nЭто только отчёт. Для отправки запусти с --apply"))
            return

        sent = failed = 0
        for start in range(0, len(pending), BATCH_SIZE):
            chunk = [card_with_tnved(card) for card in pending[start:start + BATCH_SIZE]]
            response = api.update_item(data=chunk)
            if not isinstance(response, dict) or response.get("error"):
                failed += len(chunk)
                error = response.get("errorText") if isinstance(response, dict) else response
                self.stderr.write(self.style.ERROR(f"Пачка с {start}: WB вернул ошибку: {error}"))
            else:
                sent += len(chunk)
                self.stdout.write(f"Отправлено: {sent} из {len(pending)}")
            if start + BATCH_SIZE < len(pending):
                time.sleep(PAUSE_SECONDS)

        self.stdout.write(self.style.SUCCESS(
            f"\nОтправлено: {sent}, не принято пачками: {failed}. Изменения на WB "
            "применяются до 30 минут; непрошедшие карточки — в v2/cards/error/list. "
            "Повторный запуск возьмёт только карточки, где ТН ВЭД так и не появился."
        ))

    def _collect_cards(self, api):
        """Все карточки WB. None — если выгрузка сорвалась."""
        cards = []
        cursor = None
        while True:
            data = api.get_items(param="all", cursor=cursor)
            page = data.get("cards") if isinstance(data, dict) else None
            if page is None:
                self.stderr.write(self.style.ERROR(
                    "WB не отдал список карточек — прерываю, иначе обновление "
                    "прошло бы по неполному списку."
                ))
                return None
            cards.extend(page)

            cursor_data = data.get("cursor") or {}
            if len(page) < 100 or "nmID" not in cursor_data or "updatedAt" not in cursor_data:
                return cards
            cursor = {
                "updatedAt": cursor_data["updatedAt"],
                "nmID": cursor_data["nmID"],
                "limit": 100,
            }
