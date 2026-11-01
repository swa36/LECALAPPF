import csv
import time

from django.core.management.base import BaseCommand

from catalog.models import Product
from src.lekala_class.class_marketplace.WB import WBItemCard
from src.lekala_class.class_marketplace.WBItem import (
    GLASS_SUBJECT_ID,
    GLASS_TNVED_CODE,
    TNVED_CODE,
    card_is_done,
    card_with_tnved,
    glass_category_ids,
    target_tnved,
)

# v2/cards/update: до 3000 карточек в запросе, лимит 10 запросов в минуту.
BATCH_SIZE = 100
PAUSE_SECONDS = 7


def blocked_for_documents(card):
    verdict = (card.get("documents") or {}).get("overallVerdict") or {}
    return bool(verdict.get("reason"))


class Command(BaseCommand):
    help = (
        "Приводит карточки WB к виду, который не блокируется по 289-ФЗ: "
        f"плёнкам — ТН ВЭД {TNVED_CODE}, стёклам в предмете {GLASS_SUBJECT_ID} — "
        f"{GLASS_TNVED_CODE}, всем — отметка «документы не требуются» "
        "(excludeDocuments). Стёклам, ещё лежащим в 6466, ТН ВЭД не ставится — "
        "только отметка; их надо перенести в 9226 в кабинете (список — --glass-csv). "
        "Карточка берётся с WB как есть. По умолчанию только отчёт, отправка — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Отправить на WB (без флага — только отчёт)")
        parser.add_argument("--limit", type=int, default=None,
                            help="Обработать только первые N карточек")
        parser.add_argument("--show", type=int, default=10,
                            help="Сколько карточек показать в отчёте (0 — все)")
        parser.add_argument("--glass-csv", default=None,
                            help="Сохранить в CSV стёкла, которые надо перенести в предмет 9226")

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

        unknown, done, pending = [], [], []
        groups = {"film": 0, "glass_9226": 0, "glass_6466": 0}
        glass_to_move = []
        for card in cards:
            code_vendor = card.get("vendorCode")
            if code_vendor not in articles:
                unknown.append(card)
                continue
            is_glass_card = code_vendor in glass
            code = target_tnved(card, is_glass_card)
            if is_glass_card and code is None:
                glass_to_move.append(card)
            if card_is_done(card, code):
                done.append(card)
                continue
            pending.append((card, code))
            if not is_glass_card:
                groups["film"] += 1
            elif code is None:
                groups["glass_6466"] += 1
            else:
                groups["glass_9226"] += 1

        blocked = sum(1 for card, _ in pending if blocked_for_documents(card))
        self.stdout.write(
            f"Карточек на WB: {len(cards)}\n"
            f"    уже в порядке: {len(done)}\n"
            f"    артикула нет в базе, пропускаю: {len(unknown)}\n"
            f"    к обновлению: {len(pending)}, из них заблокированы WB за документы: {blocked}\n"
            f"        плёнки → ТН ВЭД {TNVED_CODE} + excludeDocuments: {groups['film']}\n"
            f"        стёкла в {GLASS_SUBJECT_ID} → ТН ВЭД {GLASS_TNVED_CODE} + excludeDocuments: "
            f"{groups['glass_9226']}\n"
            f"        стёкла в 6466 → только excludeDocuments: {groups['glass_6466']}\n"
            f"Стёкол ещё не в предмете {GLASS_SUBJECT_ID} (перенести в кабинете): {len(glass_to_move)}"
        )
        for card in unknown[:20]:
            self.stdout.write(
                f"    нет в базе: nmID {card['nmID']} {card.get('vendorCode')} {card.get('title', '')[:50]}"
            )

        if options["glass_csv"]:
            self._write_glass_csv(options["glass_csv"], glass_to_move)

        if options["limit"] is not None:
            pending = pending[:options["limit"]]
            self.stdout.write(f"Ограничение --limit: берём первые {len(pending)}")
        if not pending:
            self.stdout.write(self.style.SUCCESS("Обновлять нечего"))
            return

        # заблокированные — первыми, чтобы быстрее вернулись в продажу
        pending.sort(key=lambda item: not blocked_for_documents(item[0]))

        show = options["show"]
        for card, code in pending if show == 0 else pending[:show]:
            self.stdout.write(
                f"    nmID {card['nmID']:<12} {card.get('vendorCode', '')[:24]:<24} "
                f"ТН ВЭД {code or '—':<10} {card.get('title', '')[:45]}"
            )
        if show and len(pending) > show:
            self.stdout.write(f"    ... ещё {len(pending) - show}, весь список — с --show 0")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("\nЭто только отчёт. Для отправки запусти с --apply"))
            return

        sent = failed = 0
        for start in range(0, len(pending), BATCH_SIZE):
            chunk = [card_with_tnved(card, code) for card, code in pending[start:start + BATCH_SIZE]]
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
            "применяются до 30 минут; непрошедшие карточки — POST v2/cards/error/list. "
            "Повторный запуск возьмёт только карточки, где изменения так и не появились."
        ))

    def _write_glass_csv(self, path, cards):
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["nmID", "Артикул продавца", "Предмет сейчас", "Наименование"])
            for card in cards:
                writer.writerow([card["nmID"], card.get("vendorCode"),
                                 card.get("subjectName"), card.get("title")])
        self.stdout.write(f"Список стёкол для переноса в {GLASS_SUBJECT_ID}: {path} ({len(cards)} шт.)")

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
