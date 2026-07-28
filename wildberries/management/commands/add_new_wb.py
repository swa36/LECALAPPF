from django.core.management.base import BaseCommand

from wildberries.tasks import add_new_item_wb, candidates_for_wb


class Command(BaseCommand):
    help = (
        "Заводит карточки на WB для товаров, которых там ещё нет. Архивные и "
        "категорию «Инструмент и оборудование» не берёт. Товары без "
        "обязательных атрибутов (material, width, length, equipment, color) "
        "или без розничной цены пропускает и показывает отдельно. "
        "По умолчанию только отчёт, отправка — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Отправить карточки на WB (без флага — только отчёт)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Взять только первые N товаров — удобно для пробного запуска",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=20,
            help="Сколько строк показать в каждом списке (0 — все)",
        )

    def handle(self, *args, **options):
        limit = options["limit"] or None
        total = candidates_for_wb().count()
        self.stdout.write(f"Товаров без карточки WB: {total}")
        if not total:
            return
        if limit:
            self.stdout.write(f"Ограничение --limit: берём первые {limit}")

        report = {}
        sent = add_new_item_wb(dry_run=not options["apply"], limit=limit, report=report)
        skipped = report.get("skipped", [])
        taken = report.get("taken", [])

        show = options["show"]
        if taken:
            self.stdout.write(
                f"\n=== Артикул уже занят карточкой на WB: {len(taken)} ==="
            )
            self.stdout.write(
                "    Карточка на WB есть, а связки WBData нет. Заводить нельзя — "
                "WB ответит «vendor code is used in other cards».\n"
                "    Подтяни связки: manage.py shell -c "
                '"from wildberries.tasks import set_id_wb; set_id_wb()"'
            )
            rows = taken if show == 0 else taken[:show]
            for product in rows:
                self.stdout.write(
                    f"    {product.article_1C[:24]:<24} {product.name[:45]}"
                )
            if show and len(taken) > show:
                self.stdout.write(f"    ... ещё {len(taken) - show}, весь список — с --show 0")

        if skipped:
            self.stdout.write(f"\n=== Пропущены: {len(skipped)} ===")
            rows = skipped if show == 0 else skipped[:show]
            for product, reason in rows:
                self.stdout.write(
                    f"    {product.article_1C[:24]:<24} {reason:<22} {product.name[:40]}"
                )
            if show and len(skipped) > show:
                self.stdout.write(f"    ... ещё {len(skipped) - show}, весь список — с --show 0")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nЭто только отчёт. Готовы к заведению: {sent}. "
                    "Для отправки запусти с --apply"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"\nОтправлено карточек на WB: {sent}. "
                "Создание идёт не мгновенно: непрошедшие смотри в "
                "v2/cards/error/list, появившиеся — подтяни через set_id_wb."
            )
        )
