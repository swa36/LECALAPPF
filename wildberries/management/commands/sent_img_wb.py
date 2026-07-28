from django.core.management.base import BaseCommand

from wildberries.tasks import sent_img_wb

PARAMS = ('withoutImg', 'all', 'withImg')


class Command(BaseCommand):
    help = (
        "Заливает изображения с сайта на карточки WB. Какие карточки обходить — "
        "задаётся --param, по умолчанию withoutImg: им картинки и нужны. "
        "По умолчанию только отчёт, отправка — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--param",
            choices=PARAMS,
            default="withoutImg",
            help="Какие карточки обходить: withoutImg (по умолчанию), all, withImg",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Отправить изображения на WB (без флага — только отчёт)",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=20,
            help="Сколько пропущенных показать (0 — все)",
        )

    def handle(self, *args, **options):
        param = options["param"]
        self.stdout.write(f"Обход карточек WB: {param}\n")

        report = {}
        sent = sent_img_wb(
            param=param, dry_run=not options["apply"], report=report
        )
        skipped = report.get("skipped", [])

        if skipped:
            self.stdout.write(f"\n=== Пропущены: {len(skipped)} ===")
            show = options["show"]
            rows = skipped if show == 0 else skipped[:show]
            for code, reason in rows:
                self.stdout.write(f"    {str(code)[:24]:<24} {reason}")
            if show and len(skipped) > show:
                self.stdout.write(f"    ... ещё {len(skipped) - show}, весь список — с --show 0")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nЭто только отчёт. Карточек с готовыми изображениями: {sent}. "
                    "Для отправки запусти с --apply"
                )
            )
            return

        self.stdout.write(self.style.SUCCESS(f"\nИзображения отправлены: {sent}"))
