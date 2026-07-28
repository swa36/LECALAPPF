from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import ProtectedError

from catalog.models import Category, Product
from src.lekala_class.class_1C.ExChange1C import ExChange1C

# Доля устаревших категорий, выше которой команда не станет ничего удалять
# без --force: похоже на сбой выгрузки, а не на реальную чистку в 1С.
SANITY_LIMIT = 0.2


class Command(BaseCommand):
    help = (
        "Удаляет категории, которых больше нет в выгрузке 1С — их перенесли "
        "в «Удалено(архив)», и сервис их не отдаёт. Товары такой категории "
        "переносятся на актуального двойника с тем же названием. "
        "По умолчанию только отчёт, изменения — с --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Выполнить перенос товаров и удаление (без флага — только отчёт)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Игнорировать защиту от массового удаления",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]

        items = ExChange1C().get_category().get("value", [])
        if not items:
            self.stderr.write(
                self.style.ERROR(
                    "1С не вернула ни одной категории — прерываю, "
                    "иначе удалились бы все категории сайта."
                )
            )
            return

        api_uuids = {i["ref_key"] for i in items}
        total = Category.objects.count()
        self.stdout.write(f"Категорий в 1С: {len(api_uuids)}, в БД сайта: {total}")

        stale = [c for c in Category.objects.all() if str(c.uuid_1C) not in api_uuids]
        if not stale:
            self.stdout.write(self.style.SUCCESS("Лишних категорий нет, дерево совпадает с 1С"))
            return

        self.stdout.write(f"Категорий без соответствия в 1С: {len(stale)}\n")

        plan = []
        for cat in sorted(stale, key=lambda c: (c.level, c.name)):
            products = list(cat.category.all())
            kids = list(cat.children.all())
            twin = self._find_twin(cat, api_uuids)

            if products and twin is None:
                action = "ПРОПУСК: есть товары, актуальный двойник не найден"
            elif kids and any(str(k.uuid_1C) in api_uuids for k in kids):
                action = "ПРОПУСК: есть живые подкатегории"
            elif products:
                action = f"товары ({len(products)}) → «{twin.name}» [{twin.uuid_1C}], затем удаление"
            else:
                action = "удаление"

            plan.append((cat, products, twin, action))

            parent = cat.parent.name if cat.parent else "— корень —"
            self.stdout.write(
                f"  «{cat.name}» (родитель: {parent})\n"
                f"      uuid: {cat.uuid_1C}  товаров: {len(products)}  подкатегорий: {len(kids)}\n"
                f"      {action}"
            )

        removable = [row for row in plan if not row[3].startswith("ПРОПУСК")]
        self.stdout.write(
            f"\nК удалению: {len(removable)}, пропущено: {len(plan) - len(removable)}"
        )

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("\nЭто только отчёт. Для выполнения запусти с --apply")
            )
            return

        if not options["force"] and total and len(removable) / total > SANITY_LIMIT:
            self.stderr.write(
                self.style.ERROR(
                    f"Под удаление попало {len(removable)} из {total} категорий "
                    f"(> {SANITY_LIMIT:.0%}). Похоже на сбой выгрузки. "
                    "Если это действительно так задумано — добавь --force."
                )
            )
            return

        moved = 0
        deleted = 0
        with transaction.atomic():
            for cat, products, twin, action in removable:
                if products:
                    moved += Product.objects.filter(category=cat).update(category=twin)
                try:
                    cat.delete()
                    deleted += 1
                except ProtectedError as exc:
                    self.stderr.write(
                        self.style.WARNING(f"  «{cat.name}» не удалена: {exc}")
                    )

            Category.objects.rebuild()

        self.stdout.write(
            self.style.SUCCESS(
                f"\nГотово. Товаров перенесено: {moved}, категорий удалено: {deleted}. "
                f"Осталось категорий: {Category.objects.count()}"
            )
        )

    def _find_twin(self, cat, api_uuids):
        """Актуальная категория с тем же названием — куда переехали товары."""
        candidates = [
            twin
            for twin in Category.objects.filter(name=cat.name).exclude(pk=cat.pk)
            if str(twin.uuid_1C) in api_uuids
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Двойников много (например, «AUDI» есть в каждой ветке дерева) —
        # выбираем того, у кого совпадает родитель, иначе решать вручную.
        if cat.parent:
            same_parent = [
                twin
                for twin in candidates
                if twin.parent and twin.parent.name == cat.parent.name
            ]
            if len(same_parent) == 1:
                return same_parent[0]
        return None
